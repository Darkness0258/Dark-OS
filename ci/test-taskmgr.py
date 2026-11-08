#!/usr/bin/env python3
"""Task Manager: the /proc reader on a fake tree, the end-task rules, then the window.

    xvfb-run -a dbus-run-session -- python3 ci/test-taskmgr.py
"""
import importlib.util
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

from darkos_shell import procinfo  # noqa: E402  (GTK-free)

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

    GTK = Gtk.init_check()[0]
except (ImportError, ValueError):
    GTK = False


def make_proc(root, pid, comm, *, state="S", ppid=1, utime=0, stime=0, threads=1, start=100,
              rss_pages=0, uid=1000, argv=None, readable=True):
    d = Path(root) / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    if readable:
        (d / "stat").write_text(
            f"{pid} ({comm}) {state} {ppid} 0 0 0 0 0 0 0 0 0 {utime} {stime} 0 0 20 0 "
            f"{threads} 0 {start} 0 {rss_pages}\n")
    (d / "status").write_text(f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in (argv or [])) + (b"\0" if argv else b""))


def write_global(root, user=100, idle=900, mem_total_kb=8_000_000, mem_avail_kb=6_000_000,
                 swap_total_kb=2_000_000, swap_free_kb=1_500_000):
    Path(root, "stat").write_text(f"cpu  {user} 0 0 {idle} 0 0 0 0 0 0\n")
    Path(root, "meminfo").write_text(
        f"MemTotal: {mem_total_kb} kB\nMemFree: 1 kB\nMemAvailable: {mem_avail_kb} kB\n"
        f"SwapTotal: {swap_total_kb} kB\nSwapFree: {swap_free_kb} kB\n")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def sampler_for(root, clock):
    return procinfo.Sampler(str(root), clock=clock, clk_tck=100, page_size=4096,
                            lookup_user=lambda uid: {0: "root", 1000: "hamza"}.get(uid, str(uid)))


class ProcReaderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.clock = Clock()
        write_global(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def by_pid(self, snap):
        return {p.pid: p for p in snap.procs}

    def test_stat_parsing_survives_spaces_and_parentheses_in_the_name(self):
        text = "123 (Web Content (x)) S 1 0 0 0 0 0 0 0 0 0 7 5 0 0 20 0 4 0 999 0 250\n"
        comm, state, ppid, ticks, threads, start, rss = procinfo.parse_stat(text)
        self.assertEqual((comm, state, ppid, ticks, threads, start, rss),
                         ("Web Content (x)", "S", 1, 12, 4, 999, 250))

    def test_a_process_is_read_with_owner_command_and_memory(self):
        make_proc(self.root, 42, "python3", rss_pages=2560, threads=3,
                  argv=["python3", "/usr/local/bin/darkos-clock.py"])
        snap = sampler_for(self.root, self.clock).sample()
        p = self.by_pid(snap)[42]
        self.assertEqual(p.name, "darkos-clock.py")
        self.assertEqual(p.cmdline, "python3 /usr/local/bin/darkos-clock.py")
        self.assertEqual((p.user, p.uid, p.threads), ("hamza", 1000, 3))
        self.assertEqual(p.rss, 2560 * 4096)

    def test_kernel_threads_with_no_command_line_show_their_name_in_brackets(self):
        make_proc(self.root, 2, "kthreadd", uid=0, argv=[])
        p = self.by_pid(sampler_for(self.root, self.clock).sample())[2]
        self.assertEqual((p.name, p.cmdline, p.user), ("kthreadd", "[kthreadd]", "root"))

    def test_cpu_is_zero_on_the_first_sample_then_comes_from_the_difference(self):
        make_proc(self.root, 10, "busy", utime=100)
        make_proc(self.root, 11, "idle", utime=100)
        sampler = sampler_for(self.root, self.clock)
        first = self.by_pid(sampler.sample())
        self.assertEqual((first[10].cpu, first[11].cpu), (0.0, 0.0))
        self.clock.now += 2.0
        make_proc(self.root, 10, "busy", utime=100 + 100)   # 100 ticks over 2 s at 100 Hz = 50%
        second = self.by_pid(sampler.sample())
        self.assertAlmostEqual(second[10].cpu, 50.0, places=3)
        self.assertEqual(second[11].cpu, 0.0)

    def test_a_reused_pid_does_not_inherit_the_old_processes_ticks(self):
        make_proc(self.root, 10, "old", utime=5000, start=100)
        sampler = sampler_for(self.root, self.clock)
        sampler.sample()
        self.clock.now += 1.0
        make_proc(self.root, 10, "new", utime=3, start=777)   # same PID, different process
        p = self.by_pid(sampler.sample())[10]
        self.assertEqual(p.cpu, 0.0)
        self.assertEqual(p.name, "new", "static info must be re-read for the new process")

    def test_exited_and_unreadable_processes_are_dropped_not_fatal(self):
        make_proc(self.root, 10, "stays")
        make_proc(self.root, 11, "leaves")
        make_proc(self.root, 12, "denied", readable=False)   # no stat file: vanished mid-read
        (Path(self.root) / "self").mkdir()
        sampler = sampler_for(self.root, self.clock)
        self.assertEqual(sorted(self.by_pid(sampler.sample())), [10, 11])
        import shutil
        shutil.rmtree(Path(self.root) / "11")
        self.assertEqual(sorted(self.by_pid(sampler.sample())), [10])
        self.assertEqual(sorted(sampler._static), [10], "caches must not keep exited processes")

    def test_machine_cpu_and_memory_totals(self):
        make_proc(self.root, 10, "x")
        sampler = sampler_for(self.root, self.clock)
        sampler.sample()
        self.clock.now += 1.0
        write_global(self.root, user=100 + 30, idle=900 + 70)   # 30 busy of 100 new ticks
        snap = sampler.sample()
        self.assertAlmostEqual(snap.cpu_percent, 30.0, places=3)
        self.assertEqual(snap.mem_total, 8_000_000 * 1024)
        self.assertEqual(snap.mem_used, 2_000_000 * 1024)
        self.assertEqual((snap.swap_total, snap.swap_used), (2_000_000 * 1024, 500_000 * 1024))

    def test_display_names(self):
        n = procinfo.display_name
        self.assertEqual(n("python3", ["python3", "/usr/local/bin/darkos-store.py"]), "darkos-store.py")
        self.assertEqual(n("python3.12", ["python3.12", "-u", "/x/app.py"]), "app.py")
        self.assertEqual(n("bash", ["bash", "/home/u/run.sh"]), "run.sh")
        self.assertEqual(n("firefox", ["firefox", "--private"]), "firefox")
        # Not an interpreter just because the name starts with "sh" or "python":
        self.assertEqual(n("shotwell", ["shotwell", "/pics/photo.jpg"]), "shotwell")
        self.assertEqual(n("pythonista", ["pythonista", "doc.txt"]), "pythonista")
        self.assertEqual(n("python3", []), "python3")

    def test_search_matches_name_command_pid_and_user(self):
        p = procinfo.Proc(4321, 1, "darkos-clock.py", "python3 /usr/local/bin/darkos-clock.py",
                          "S", 1000, "hamza", 0, 0, 1, 1)
        for query in ("", "  ", "CLOCK", "local/bin", "4321", "ham"):
            self.assertTrue(procinfo.matches(p, query), query)
        for query in ("firefox", "432", "root"):
            self.assertFalse(procinfo.matches(p, query), query)

    def test_only_the_owner_or_root_may_signal_and_the_system_is_protected(self):
        mine = procinfo.Proc(500, 1, "x", "x", "S", 1000, "hamza", 0, 0, 1, 1)
        theirs = procinfo.Proc(501, 1, "x", "x", "S", 0, "root", 0, 0, 1, 1)
        init = procinfo.Proc(1, 0, "systemd", "systemd", "S", 0, "root", 0, 0, 1, 1)
        self.assertEqual(procinfo.can_signal(mine, 1000), (True, ""))
        ok, why = procinfo.can_signal(theirs, 1000)
        self.assertFalse(ok)
        self.assertIn("root", why)
        self.assertTrue(procinfo.can_signal(theirs, 0)[0])
        self.assertFalse(procinfo.can_signal(init, 0)[0], "not even root may end PID 1 from here")

    def test_big_consequence_processes_carry_a_warning(self):
        def proc(name, cmd):
            return procinfo.Proc(9, 1, name, cmd, "S", 1000, "u", 0, 0, 1, 1)
        self.assertIn("whole session", procinfo.warning_for(proc("Hyprland", "Hyprland")))
        self.assertIn("dock", procinfo.warning_for(
            proc("darkos-shell.py", "python /usr/local/bin/darkos-shell.py")))
        self.assertEqual(procinfo.warning_for(proc("firefox", "firefox")), "")

    def test_end_task_sends_the_right_signal_and_reports_every_outcome(self):
        sent = []
        self.assertEqual(procinfo.end_task(900, kill=lambda pid, sig: sent.append((pid, sig)), own_pid=1),
                         (True, "Asked it to quit."))
        self.assertEqual(procinfo.end_task(900, force=True, kill=lambda pid, sig: sent.append((pid, sig)),
                                           own_pid=1)[0], True)
        self.assertEqual(sent, [(900, signal.SIGTERM), (900, signal.SIGKILL)])

        def raiser(exc):
            def kill(pid, sig):
                raise exc
            return kill
        self.assertTrue(procinfo.end_task(900, kill=raiser(ProcessLookupError()), own_pid=1)[0])
        ok, msg = procinfo.end_task(900, kill=raiser(PermissionError()), own_pid=1)
        self.assertFalse(ok)
        self.assertIn("another user", msg)
        ok, msg = procinfo.end_task(900, kill=raiser(OSError(5, "Input/output error")), own_pid=1)
        self.assertFalse(ok)
        self.assertIn("Input/output error", msg)

    def test_end_task_refuses_pid_one_and_itself_without_calling_kill(self):
        def boom(pid, sig):
            raise AssertionError("must not be called")
        self.assertFalse(procinfo.end_task(1, kill=boom)[0])
        self.assertFalse(procinfo.end_task(0, kill=boom)[0])
        ok, msg = procinfo.end_task(os.getpid(), kill=boom)
        self.assertFalse(ok)
        self.assertIn("Task Manager", msg)

    def test_the_real_proc_is_readable_and_sees_this_process_burn_cpu(self):
        sampler = procinfo.Sampler()
        first = sampler.sample()
        me = {p.pid: p for p in first.procs}.get(os.getpid())
        self.assertIsNotNone(me, "own process missing from the real /proc")
        self.assertGreater(len(first.procs), 3)
        self.assertGreater(first.mem_total, 0)
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            sum(i * i for i in range(2000))
        second = {p.pid: p for p in sampler.sample().procs}[os.getpid()]
        self.assertGreater(second.cpu, 5.0)

    def test_the_readers_never_fork(self):
        import ast
        for name in ("darkos_shell/procinfo.py", "darkos-taskmgr.py"):
            tree = ast.parse((BIN / name).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
                elif isinstance(node, ast.Attribute) and node.attr in ("system", "popen"):
                    self.fail(f"{name} calls os.{node.attr}: read /proc, do not run `ps`")
            self.assertNotIn("subprocess", imported, f"{name} must read /proc, not run `ps`")


class FakeSampler:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = 0
        self.threads = set()
        self.gate = None
        self.fail = False
        self.started = threading.Event()

    def sample(self):
        self.calls += 1
        self.threads.add(threading.current_thread())
        self.started.set()
        if self.gate:
            self.gate.wait(5)
        if self.fail:
            raise RuntimeError("boom")
        return self.snapshots[min(self.calls, len(self.snapshots)) - 1]


def P(pid, name, cpu=0.0, uid=1000, rss=10 * 1024 * 1024, cmd=None, user=None):
    return procinfo.Proc(pid, 1, name, cmd or name, "S", uid, user or ("hamza" if uid == 1000 else "root"),
                         0, rss, 1, 1, cpu)


def snap(*procs, cpu=12.0):
    return procinfo.Snapshot(list(procs), cpu, 8 * 2**30, 2 * 2**30, 0, 0, time.monotonic())


def pump(until, timeout=3.0):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        while ctx.iteration(False):
            pass
        if until():
            return True
        time.sleep(0.01)
    return until()


def load_module():
    spec = importlib.util.spec_from_file_location("darkos_taskmgr_app", BIN / "darkos-taskmgr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(GTK, "no display (run under xvfb-run)")
class TaskManagerWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()
        cls.app = Gtk.Application(application_id="org.darkos.TaskManagerTest",
                                  flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)

    def setUp(self):
        self.kills = []
        self.base = snap(P(100, "firefox", cpu=40.0), P(101, "darkos-notes.py", cpu=1.5),
                         P(102, "Hyprland", cpu=3.0), P(200, "NetworkManager", cpu=0.2, uid=0),
                         P(201, "sshd", cpu=0.0, uid=0))

    def tearDown(self):
        for win in list(self.app.get_windows()):
            win.destroy()

    def window(self, sampler=None, show=False, interval_ms=60):
        sampler = sampler or FakeSampler([self.base])

        def killer(pid, force=False):
            self.kills.append((pid, force))
            return True, "Force quit sent." if force else "Asked it to quit."

        win = self.mod.TaskManagerWindow(self.app, sampler=sampler, killer=killer, my_uid=1000,
                                         interval_ms=interval_ms)
        if show:
            win.show_all()
        return win

    def visible_pids(self, win):
        return [row[self.mod.COL_PID] for row in win.sorted]

    def select(self, win, pid):
        for row in win.sorted:
            if row[self.mod.COL_PID] == pid:
                win.tree.get_selection().select_iter(row.iter)
                return
        self.fail(f"pid {pid} is not listed")

    def test_the_table_uses_the_design_system_list_style(self):
        win = self.window()
        self.assertTrue(win.tree.get_style_context().has_class("darkos-list"),
                        "an unstyled TreeView is a white grid with near-white text on Calm Dark")

    def test_default_view_is_my_processes_sorted_by_cpu_descending(self):
        win = self.window()
        win.apply_snapshot(self.base)
        self.assertEqual(self.visible_pids(win), [100, 102, 101])
        self.assertEqual(win.count_label.get_text(), "5 processes")
        self.assertEqual(win.cpu_label.get_text(), "CPU  12%")
        self.assertIn("2.0 GB of 8.0 GB", win.mem_label.get_text())

    def test_all_users_adds_the_system_processes(self):
        win = self.window()
        win.apply_snapshot(self.base)
        win.all_users_check.set_active(True)
        self.assertEqual(sorted(self.visible_pids(win)), [100, 101, 102, 200, 201])

    def test_search_filters_by_name_pid_and_user(self):
        win = self.window()
        win.apply_snapshot(self.base)
        win.all_users_check.set_active(True)
        win.search.set_text("fire")
        win.filter.refilter()
        self.assertEqual(self.visible_pids(win), [100])
        win.search.set_text("201")
        win.filter.refilter()
        self.assertEqual(self.visible_pids(win), [201])
        win.search.set_text("root")
        win.filter.refilter()
        self.assertEqual(sorted(self.visible_pids(win)), [200, 201])

    def test_my_process_can_be_ended_without_a_dialog(self):
        win = self.window()
        win.apply_snapshot(self.base)
        win._confirm = lambda *a: self.fail("an ordinary End task must not ask")
        self.select(win, 101)
        self.assertTrue(win.end_btn.get_sensitive())
        win.end_btn.clicked()
        self.assertEqual(self.kills, [(101, False)])
        self.assertIn("darkos-notes.py (101): Asked it to quit.", win.status.get_text())

    def test_force_quit_always_asks_and_respects_cancel(self):
        win = self.window()
        win.apply_snapshot(self.base)
        self.select(win, 101)
        asked = []
        win._confirm = lambda title, text, ok: asked.append((title, ok)) or False
        win.force_btn.clicked()
        self.assertEqual(self.kills, [], "declined: nothing may be sent")
        self.assertEqual(asked, [("Force quit darkos-notes.py?", "Force quit")])
        win._confirm = lambda *a: True
        win.force_btn.clicked()
        self.assertEqual(self.kills, [(101, True)])

    def test_ending_the_compositor_needs_a_confirmation_even_for_a_plain_end_task(self):
        win = self.window()
        win.apply_snapshot(self.base)
        self.select(win, 102)
        seen = []
        win._confirm = lambda title, text, ok: seen.append(text) or False
        win.end_btn.clicked()
        self.assertEqual(self.kills, [])
        self.assertIn("whole session", seen[0])
        win._confirm = lambda *a: True
        win.end_btn.clicked()
        self.assertEqual(self.kills, [(102, False)])

    def test_someone_elses_process_cannot_be_ended_and_the_reason_is_shown(self):
        win = self.window()
        win.apply_snapshot(self.base)
        win.all_users_check.set_active(True)
        self.select(win, 200)
        self.assertFalse(win.end_btn.get_sensitive())
        self.assertFalse(win.force_btn.get_sensitive())
        self.assertIn("root", win.status.get_text())
        win.end_selected(force=False)
        self.assertEqual(self.kills, [])

    def test_ending_this_task_manager_is_refused_by_the_real_rules(self):
        me = P(os.getpid(), "darkos-taskmgr.py")
        win = self.mod.TaskManagerWindow(self.app, sampler=FakeSampler([snap(me)]), my_uid=os.getuid())
        win.apply_snapshot(snap(P(os.getpid(), "darkos-taskmgr.py", uid=os.getuid())))
        self.select(win, os.getpid())
        win.end_btn.clicked()
        self.assertIn("Close its window", win.status.get_text())

    def test_refresh_updates_in_place_keeping_the_selection_and_dropping_exited_rows(self):
        win = self.window()
        win.apply_snapshot(self.base)
        self.select(win, 101)
        before = win.iters[101]
        later = snap(P(100, "firefox", cpu=0.5), P(101, "darkos-notes.py", cpu=77.0))   # 102 exited
        win.apply_snapshot(later)
        self.assertEqual(win.selected_proc().pid, 101, "selection must survive a refresh")
        self.assertEqual(self.visible_pids(win), [101, 100], "re-sorted by the new CPU values")
        self.assertNotIn(102, win.procs)
        self.assertEqual(len(win.store), 2 + 0, "exited and filtered rows are removed from the model")
        self.assertIs(win.iters[101], before, "the row was updated, not replaced")

    def test_sampling_happens_on_a_worker_thread_and_never_overlaps(self):
        sampler = FakeSampler([self.base])
        sampler.gate = threading.Event()
        win = self.window(sampler)
        win.request_sample()
        self.assertTrue(sampler.started.wait(2))
        win.request_sample()
        win.request_sample()
        time.sleep(0.1)
        self.assertEqual(sampler.calls, 1, "a slow sample must not stack up more samples")
        sampler.gate.set()
        self.assertTrue(pump(lambda: win.snapshot is not None))
        self.assertNotIn(threading.main_thread(), sampler.threads)

    def test_a_failing_reader_shows_a_message_and_the_window_keeps_working(self):
        sampler = FakeSampler([self.base])
        sampler.fail = True
        win = self.window(sampler)
        win.request_sample()
        self.assertTrue(pump(lambda: "Could not read" in win.status.get_text()))
        sampler.fail = False
        win.request_sample()
        self.assertTrue(pump(lambda: win.snapshot is not None))

    def test_timer_runs_only_while_the_window_is_shown_and_not_paused(self):
        self.mod.FIRST_REFRESH_MS = 120   # the quick second sample, shortened for the test
        sampler = FakeSampler([self.base])
        win = self.window(sampler, show=True, interval_ms=40)
        self.assertTrue(pump(lambda: win.timer_id is not None), "shown: sampling must start")
        self.assertTrue(pump(lambda: sampler.calls >= 3))
        win.hide()                                # minimized/hidden behaves the same way
        pump(lambda: False, 0.1)                  # let a sample already in flight finish
        self.assertIsNone(win.timer_id)
        self.assertIsNone(win._quick_id)
        calls = sampler.calls
        pump(lambda: False, 0.4)                  # longer than the quick-sample delay
        self.assertEqual(sampler.calls, calls, "hidden: no sampling at all, not even the quick one")
        win.show()
        self.assertTrue(pump(lambda: sampler.calls > calls), "shown again: sampling resumes")
        win.pause_btn.set_active(True)
        pump(lambda: False, 0.1)
        self.assertIsNone(win.timer_id)
        self.assertIsNone(win._quick_id)
        calls = sampler.calls
        pump(lambda: False, 0.4)
        self.assertEqual(sampler.calls, calls, "paused: no sampling")
        win.pause_btn.set_active(False)
        self.assertTrue(pump(lambda: sampler.calls > calls))

    def test_ending_a_task_while_paused_does_not_resume_sampling(self):
        sampler = FakeSampler([self.base])
        win = self.window(sampler, show=True, interval_ms=40)
        pump(lambda: sampler.calls >= 1)
        win.pause_btn.set_active(True)
        pump(lambda: False, 0.1)
        win.apply_snapshot(self.base)
        self.select(win, 101)
        calls = sampler.calls
        win.end_btn.clicked()
        self.assertEqual(self.kills, [(101, False)])
        pump(lambda: False, 1.0)                 # past the 700 ms follow-up refresh
        self.assertEqual(sampler.calls, calls, "paused: the post-kill refresh must stay quiet too")

    def test_destroying_the_window_stops_everything(self):
        sampler = FakeSampler([self.base])
        win = self.window(sampler, show=True, interval_ms=30)
        pump(lambda: sampler.calls >= 1)
        win.destroy()
        calls = sampler.calls
        pump(lambda: False, 0.25)
        self.assertEqual(sampler.calls, calls)

    def test_keyboard_delete_ends_the_task_and_ctrl_f_searches(self):
        win = self.window()
        win.apply_snapshot(self.base)
        self.select(win, 101)
        Event = lambda keyval, state=0: SimpleNamespace(keyval=keyval, state=state)  # noqa: E731
        self.assertTrue(win._on_key(win, Event(Gdk.KEY_Delete)))
        self.assertEqual(self.kills, [(101, False)])
        self.assertTrue(win._on_key(win, Event(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)))
        win.search.set_text("x")
        self.assertTrue(win._on_key(win, Event(Gdk.KEY_Escape)))
        self.assertEqual(win.search.get_text(), "")

    def test_the_launcher_binding_and_registration_exist(self):
        conf = (ROOT / "airootfs/etc/xdg/hypr/hyprland.conf").read_text(encoding="utf-8")
        self.assertIn("bind = CTRL SHIFT, Escape, exec, python /usr/local/bin/darkos-taskmgr.py", conf)
        desktop = (ROOT / "airootfs/usr/share/applications/darkos-taskmgr.desktop").read_text(encoding="utf-8")
        self.assertIn("StartupWMClass=darkos-taskmgr", desktop)


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
