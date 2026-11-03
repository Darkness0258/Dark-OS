#!/usr/bin/env python3
"""A curated catalogue over the BlackArch groups `darkos-tool-groups` already
installs by name (`sudo darkos-tool-groups install <group>`).

This is deliberately **not** a mirror of BlackArch's ~2,900 packages — "do
not reimplement security tools; make them discoverable and context-aware".
It is a maintained shortlist of well-known tools per group, so the tool
launcher has something useful to search and insert on day one; extending a
group's tool list is a one-line addition to `GROUPS` below.

Package names were checked where BlackArch's naming is not simply
"package == binary" (`hydra`, `john`, `exploitdb` -> `searchsploit`,
`theharvester` -> `theHarvester`, and the `wireshark-cli` -> `tshark` split
that is current on Arch `extra` as of this writing) rather than assumed;
the rest follow BlackArch's own documented convention of package name ==
tool name (confirmed against blackarch.org's own install examples, e.g.
`pacman -S burpsuite`).

A template's `$TARGET` is only ever *expanded into inserted, unexecuted
text* (`Vte.Terminal.feed_child`, no trailing newline) — never run. A tool
whose job isn't "point at $TARGET" (a file-based tool, an interactive
console) uses an explicit placeholder like `TARGET_FILE` or `WORDLIST_PATH`
instead, for the same reason: something to edit before pressing Enter, not
a value this module can reliably invent.
"""
from __future__ import annotations

import shlex
import shutil
import string
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    name: str
    group: str          # BlackArch group suffix, e.g. "scanner" for blackarch-scanner
    package: str        # pacman package name
    binary: str         # what the command starts with / what `which` checks
    description: str
    template: str        # may contain $TARGET, TARGET_FILE, WORDLIST_PATH, ...


GROUPS: dict[str, list[Tool]] = {
    "recon": [
        Tool("theHarvester", "recon", "theharvester", "theHarvester",
             "OSINT: emails, subdomains, hosts from search engines and public sources.",
             "theHarvester -d $TARGET -b all"),
        Tool("recon-ng", "recon", "recon-ng", "recon-ng",
             "Modular recon framework (interactive console).",
             "recon-ng"),
        Tool("WhatWeb", "recon", "whatweb", "whatweb",
             "Identifies the technology a website is built on.",
             "whatweb $TARGET"),
    ],
    "scanner": [
        Tool("nmap", "scanner", "nmap", "nmap",
             "Port/service/version scanner; the default first step against a host.",
             "nmap -sV -Pn $TARGET"),
        Tool("Nikto", "scanner", "nikto", "nikto",
             "Web server scanner for known-dangerous files, outdated software, misconfig.",
             "nikto -h $TARGET"),
        Tool("Nuclei", "scanner", "nuclei", "nuclei",
             "Template-driven vulnerability scanner.",
             "nuclei -u $TARGET"),
    ],
    "webapp": [
        Tool("sqlmap", "webapp", "sqlmap", "sqlmap",
             "Automated SQL injection detection and exploitation.",
             "sqlmap -u $TARGET --batch"),
        Tool("ffuf", "webapp", "ffuf", "ffuf",
             "Fast web fuzzer for paths, parameters, vhosts.",
             "ffuf -u $TARGET/FUZZ -w WORDLIST_PATH"),
        Tool("Gobuster", "webapp", "gobuster", "gobuster",
             "Directory/file/DNS/vhost brute-forcer.",
             "gobuster dir -u $TARGET -w WORDLIST_PATH"),
        Tool("WPScan", "webapp", "wpscan", "wpscan",
             "WordPress-specific vulnerability scanner.",
             "wpscan --url $TARGET"),
    ],
    "cracker": [
        Tool("Hydra", "cracker", "hydra", "hydra",
             "Network login brute-forcer (ssh, ftp, http-form, ...).",
             "hydra -l USER -P WORDLIST_PATH $TARGET ssh"),
        Tool("John the Ripper", "cracker", "john", "john",
             "Offline password-hash cracker.",
             "john HASH_FILE"),
        Tool("hashcat", "cracker", "hashcat", "hashcat",
             "GPU-accelerated hash cracker.",
             "hashcat -m 0 HASH_FILE WORDLIST_PATH"),
    ],
    "exploitation": [
        Tool("Metasploit", "exploitation", "metasploit", "msfconsole",
             "Exploitation framework (interactive console).",
             'msfconsole -q -x "use auxiliary/scanner/portscan/tcp; set RHOSTS $TARGET; run"'),
        Tool("searchsploit", "exploitation", "exploitdb", "searchsploit",
             "Offline Exploit-DB search.",
             "searchsploit "),
    ],
    "sniffer": [
        Tool("tshark", "sniffer", "wireshark-cli", "tshark",
             "Wireshark's CLI capture/analysis tool.",
             "tshark -i INTERFACE -w PCAP_PATH"),
        Tool("Bettercap", "sniffer", "bettercap", "bettercap",
             "Network sniffing/MITM/recon swiss-army knife (interactive).",
             "bettercap -iface INTERFACE"),
    ],
    "proxy": [
        Tool("mitmproxy", "proxy", "mitmproxy", "mitmproxy",
             "Interactive HTTPS-capable intercepting proxy.",
             "mitmproxy -p 8080"),
    ],
    "forensic": [
        Tool("binwalk", "forensic", "binwalk", "binwalk",
             "Finds and extracts embedded files/firmware inside a binary blob.",
             "binwalk -e TARGET_FILE"),
        Tool("ExifTool", "forensic", "perl-image-exiftool", "exiftool",
             "Reads/writes metadata in images, documents and more.",
             "exiftool TARGET_FILE"),
        Tool("steghide", "forensic", "steghide", "steghide",
             "Extracts/embeds data hidden in image or audio files.",
             "steghide extract -sf TARGET_FILE"),
    ],
    "wireless": [
        Tool("aircrack-ng", "wireless", "aircrack-ng", "aircrack-ng",
             "802.11 capture-file cracking suite.",
             "aircrack-ng -w WORDLIST_PATH CAPTURE_FILE.cap"),
        Tool("Wifite", "wireless", "wifite", "wifite",
             "Automates the common aircrack-ng attack sequence (interactive).",
             "wifite"),
    ],
}


def all_groups() -> list[str]:
    return list(GROUPS)


def tools_for_group(group: str) -> list[Tool]:
    return list(GROUPS.get(group, ()))


def all_tools() -> list[Tool]:
    return [tool for tools in GROUPS.values() for tool in tools]


def search(query: str) -> list[Tool]:
    """Case-insensitive substring match over name/description/group."""
    q = query.strip().lower()
    if not q:
        return all_tools()
    return [t for t in all_tools()
            if q in t.name.lower() or q in t.description.lower() or q in t.group.lower()]


def installed_packages(run=subprocess.run) -> set[str] | None:
    """The set of installed pacman package names, or `None` if that can't
    be determined (no `pacman` — true of every non-Arch dev/test box,
    including this one). `run` is injectable for tests."""
    try:
        result = run(["pacman", "-Qq"], capture_output=True, text=True, timeout=10, check=False)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def is_installed(tool: Tool, installed: set[str] | None) -> bool | None:
    """True/False against a `pacman -Qq` snapshot; falls back to `which`
    when no pacman snapshot is available (so it still says something
    correct in this dev sandbox); `None` only if neither check applies."""
    if installed is not None:
        return tool.package in installed
    if shutil.which(tool.binary):
        return True
    return None


def expand_command(template: str, target: str | None) -> str:
    """Substitutes `$TARGET` with `target` when one is set; otherwise
    leaves `$TARGET` in the text as a visible placeholder to fill in."""
    mapping = {"TARGET": target} if target else {}
    return string.Template(template).safe_substitute(mapping)


def expand_argv(template: str, target: str | None) -> list[str]:
    """`expand_command` result, shell-tokenised — for anything that wants
    an argv list instead of a feed-able string."""
    return shlex.split(expand_command(template, target))
