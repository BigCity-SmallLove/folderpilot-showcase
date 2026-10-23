# Quick start

## Run the portable application

Extract the complete Windows ZIP. Run `FolderPilot/FolderPilot.exe` and keep its `_internal` folder beside it. You do not need Python. The binary is unsigned; this stage does not provide a signing certificate or installer.

From source, use Python 3.12 with tkinter and double-click `start_windows.bat`, or run `python run_app.py`. No runtime package installation is required.

## Try the synthetic demonstration

Run `python run_app.py --demo` or `FolderPilot.exe --demo`. The opt-in demo creates only missing synthetic files under `demo-work/` in the working directory and never replaces existing ones. To regenerate a fresh demo after executing it, choose a new empty working directory; do not run repeated demonstrations against valuable files.

The source is `demo-work/inbox`, the backup target is `demo-work/backup`, and the run records folder is `demo-work/records`. All are neutral relative paths visible in real screenshots.

The default demo replaces `draft` with `final` and adds three-digit numbering. Click **Rules & monitoring** to inspect these settings, then **Preview (Dry Run)**. Five files should appear in the first fresh demo. Preview changes nothing.

To test duplicate detection, select `duplicates` in Task and preview again. The two synthetic note files belong to one duplicate group. No file is removed. Click **Export HTML** to save the full JSON plan and report under the chosen records folder.

## Rename or organize

1. Select your source and a separate records folder.
2. Choose `rename`. Find/replace affects the filename stem; the extension is preserved. Optional prefix/suffix and numbering are applied afterwards. Numbering follows sorted directory and filename traversal. For long-term repeatability, save a plan/report as evidence.
3. Alternatively choose `organize`, then `type`, `date` or `size`. Date groups use UTC modification month; size groups are under 1 MiB, under 100 MiB, and 100 MiB or more.
4. Set extension, byte-size, date and recursion filters if required. Click Preview and resolve all conflicts. Case-only Windows renames are rejected as occupied destinations.
5. Click Execute reviewed plan and read the confirmation. Run records include every attempted operation and its status. Cancelling preserves the work already completed and its recovery record.

## Backup and incremental sync

Select separate, non-overlapping source and destination directories, plus a records folder outside both. Backup produces a new complete snapshot subfolder. Each copied file is rehashed and compared with its source before success is recorded.

Sync skips identical destination content. If the source changed, its new version is copied into a sibling with `.fp-HASH` in the filename. It keeps the original destination version, and it never deletes destination-only files. This is version-preserving incremental copying, not a destructive mirror.

## Recover

Select the same original source and target directories and task mode, then click Recover and select that run's `journal.json`. For rename/organize the target is the source directory. The table displays ready, already recovered, and manual-review statuses before confirmation.

Confirm only after reviewing those paths. Ready moves restore the source if absent. Eligible output copies move into the run folder's `recovered-files/` archive. Conflicting or modified files and partial outputs stay untouched for manual review. Empty generated directories remain. Keep the entire run folder; deleting it removes recovery evidence and archived copies.

## Save rules and watch a folder

Save rules to a new JSON filename; existing files are not overwritten. Load rules, choose the folders again, and preview. Folder selections are deliberately not stored in reusable rules.

Set a watch interval (2–3600 seconds) and filters, then click Start watch. Watching only reports metadata changes and invalidates the old plan; it never executes operations. Stop watch or close the app to stop monitoring. No service or startup entry is created.

## Errors and conflicts

A changed source, occupied destination, unreadable file, invalid Windows name, link or permission problem is reported. Review warning rows and the HTML record rather than assuming every scanned item was acted on. Copy failures retain originals and may leave partial destinations. After a failure, keep the record and inspect recovery eligibility before retrying. App operation records contain local paths and should be shared only with intended recipients.
