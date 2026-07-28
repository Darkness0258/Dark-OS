# Project Overview

> Filled in once, revisited rarely. If this keeps changing, the project's definition is still moving — that's normal early on, just note it in progress-tracker.md so it's not a surprise later.

## What this is
**DarkOS** — an original, AI-first Linux OS (Arch respin + BlackArch security tools + Hyprland compositor) with a cinematic glassmorphism/HUD shell — tagline "Control Everything" — and a voice assistant that can see, hear, and control the whole system. Not a Windows/macOS/GNOME/KDE/Android clone — its own design language (JARVIS, Cyberpunk 2077, Tron Legacy, Apple VisionOS, Fluent Design, plus macOS UX patterns like Mission Control and Spaces — all reimagined, not copied) — but covering the same feature categories those systems offer. This is a real startup product, not a demo.

## Who it's for
Hamza's startup product, aimed at real users eventually. [TBD: target customer — security-focused power users, AI enthusiasts, or general consumers wanting something different from Windows/macOS? Worth nailing down alongside the build, since it shapes scope and marketing later.]

## The problem
Stock Linux desktops are functional but generic. Security distros (Kali, BlackArch) are utilitarian, not conversational or beautiful. Windows 11's AI (Copilot) and macOS are both polished but closed, and neither is woven through the OS at the level DarkOS is aiming for. Nothing combines a real installable OS + a genuinely OS-integrated AI that can operate the whole system + a security toolkit + a cinematic, original visual identity.

## Success criteria
- Boots and installs from USB on real hardware, not just a VM
- The core shell (desktop/HUD, top bar, dock, launcher, notification center, settings, lock/login/boot) runs by default, matches the reference mockup's design language, and is voice/AI-controllable end to end
- BlackArch tool groups installable from the OS's own setup, not a manual post-install step
- At least one hosted app (browser or media player) confirmed to inherit the DarkOS look automatically via Hyprland's window decorations, with zero custom reskinning needed
- The AI assistant can control at least two different native apps generically (via the accessibility tree), not through one-off hardcoded hooks per app
- Feels distinct from "Ubuntu, Windows, or macOS with a new wallpaper" within the first 60 seconds of use

## Out of scope (for now)
- Reimplementing Windows 11's or macOS's actual codebase or app catalogs — not attainable solo, or by any single team, and not the real need. Real Windows software runs via Wine/Proton/Bottles — mature, existing compatibility layers. There is no equivalent mature, legal path for running actual macOS software on generic PC hardware (Apple's license ties macOS to Apple silicon) — macOS influence here means original UI inspired by its UX patterns (Mission Control, Spaces), not binary compatibility
- Custom engines *or* custom reskins for commodity software (browser, media playback, container runtimes, git internals) — these run as the real, existing software (Linux-native or Wine-hosted), never rebuilt and never modified
- All ~90 features from the design brief as separate v1 apps — most group into a smaller set of real applications (see architecture.md's app catalog); v1 ships the daily-use core, the rest is phased
- Eye tracking, face unlock, and the phone companion app — real ideas, each its own hardware/mobile project; backlog, not v1
- A full legal/licensing review — GPL and other open-source licenses allow commercial distribution (Red Hat, Canonical, System76 all do it) but carry source-availability obligations for modified components; worth a real pass before public release, not a blocker now. Not legal advice — get an actual review before shipping commercially
