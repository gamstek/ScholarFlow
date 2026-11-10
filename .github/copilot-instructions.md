# ScholarFlow Project Charter

This file acts as the standing checklist for all future work in this repository. Before making changes or giving implementation advice, always read and follow these points.

## Always follow
- Keep the project goal centered on a **biomedical literature collection Agent**（生物医学文献采集智能体）。
- Prefer a **hybrid acquisition path**: official website first, API fallback.
- The default domain is **biomedical / life sciences**（生物医学/生命科学）；retargeting to a new domain requires explicit user approval and charter update.
- Preserve a small number of **configuration points** so the project can be retargeted to a new domain with minimal changes.
- Treat the frontend as a **modern, high-end scientific workbench**; favor clarity, polish, and a technology-style visual language.
- Keep `dev_log.md` as the single source of truth for development history.
- GitHub CI operations must use official upstream download sources. Download mirrors may be used only for local operations, supplied through local configuration or build arguments.
- When `logw1.md` or `logw2.md` exist, consolidate them into `dev_log.md` before deleting the old files.
- Avoid drift: if a request conflicts with this charter, call it out and confirm before proceeding.

## Before each task
- Re-read this charter.
- Verify the requested work still matches the generic Agent direction.
- Check whether the task changes architecture, data flow, UI style, or logging rules.
- If it does, update the charter or ask for confirmation first.

## Success criteria
- The codebase stays focused on biomedical literature, with clear extension points for other domains.
- The acquisition pipeline remains extensible.
- The UI feels polished and professional.
- Logging stays consolidated and easy to review.
