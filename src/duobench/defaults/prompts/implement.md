You are an expert front-end developer. Implement a complete WebOS based on the architecture plan below. Use vanilla JavaScript, HTML, and CSS only — no frameworks, no build step, no external dependencies or CDNs.

## Architecture plan

{plan}

## Requirements

- Write all files into the CURRENT working directory. The entry point MUST be `index.html` at the root of the working directory, opening directly in a browser with no server or build step.
- A multi-file project tree is encouraged (e.g. `css/`, `js/`, `js/apps/`). Reference files with relative paths so `file://` loading works.
- All code must be modular and well-commented.
- Implement every app and game described in the plan.
- The virtual file system must persist to localStorage.
- Include at least 3 built-in wallpapers and light/dark theme support.
- Make it visually polished — gradients, shadows, smooth transitions.
- Windows must be draggable, resizable, minimizable, maximizable, and closable.
- Games must run smoothly without blocking the UI.
- Do NOT use ES module `import`/`export` with `type="module"` unless every script is loaded via relative paths that work over `file://`. Prefer plain `<script>` tags or ensure module paths are relative.

Start by creating the project structure, then implement each module in the recommended order from the plan. Build the entire thing end to end. When you believe the build is complete and functional, say so explicitly.
