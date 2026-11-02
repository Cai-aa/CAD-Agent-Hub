# Repository split validation 2026-11-02

The EPLAN source, Skill, schemas, synthetic fixtures, tests and engineering notes
were separated into AI-CAD-Automation while retaining their relative layout.

| Check | Result |
| --- | --- |
| Standalone Windows offline and local IPC suite | 102 passed |
| C# review Add-in against the installed EPLAN 2.9 SDK | Compiled successfully; binary remains private |
| Synthetic complete snapshot example | Passed with explicit unselected-part warnings |
| Public source audit | No errors or warnings |
| Private artifacts | Not distributed; historical plans and identity snapshots remain local |

The fixed ProgramData drive prefix in the historical trial-template lookup was
replaced with the Windows CommonApplicationData special folder. It resolves the
same standard template location without embedding a drive letter.

These checks are source/package verification. No EPLAN project was opened or
modified, no new native session was certified, and no PLC or drive was operated
as part of this repository migration. The earlier per-project evidence keeps its
original date and scope.
