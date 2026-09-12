# DarkOS Cloud — Privacy Policy (draft section: AI training data)

Draft only — not legal advice, and not ready to publish as-is. Have an
actual lawyer review this before it ships anywhere. Scope is deliberately
narrow: just the AI-training-data disclosure build-plan.md's Phase 9 asks
for, written directly from what architecture.md's "DarkOS Cloud" section
already committed to — nothing added or invented beyond that.

Two placeholders below are marked `[TODO: ...]` because they're real
decisions, not writing choices — I'm not picking a retention window or
company/contact info for you.

---

## How your conversations with the DarkOS AI assistant are used

**Local and free-tier use:** if you're on the free tier or using a local
model, your conversations never leave your device. Nothing here applies.

**Cloud AI tier (paid):** when your assistant conversation is routed to
DarkOS's hosted AI model instead of running locally, that conversation may
be used to improve the model, under these limits:

- **Scoped to what you actually sent the assistant.** Only the
  conversation content you send to the cloud AI is used — never files,
  local activity, or anything else on your device that you didn't send it.
- **Time-boxed, not kept forever.** Data is collected in defined
  batches/windows for training, not retained indefinitely.
  `[TODO: state the actual retention window once decided — e.g. "conversations are retained for N days before being deleted or anonymized." Phase 9 explicitly calls for a defined window; this draft can't invent the number for you.]`
- **Disclosed up front, not buried.** This section exists specifically so
  that use isn't hidden in fine print.
- A "not used for training" tier is a plausible future add-on, not a
  current commitment — don't advertise it until it's real.

## What's stored on DarkOS's servers

Account and license/tier state, plus anything you explicitly opted into
(sync/backup, crash reports if enabled). Not a standing log of everything
your device does — the architecture doesn't collect that in the first
place, so there's nothing broader to disclose here.

## Contact

`[TODO: company/contact/entity info once decided.]`

---
*Last updated: [TODO: date] — supersedes no prior version; this is the
first draft.*
