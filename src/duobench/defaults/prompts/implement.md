You are an expert front-end developer. Implement **MiniDesk**, a small desktop-like browser app, based on the architecture plan below.

Use vanilla HTML, CSS, and JavaScript only. No frameworks, no build step, no external dependencies, no CDNs, and no ES modules. The app must work by opening `index.html` directly via `file://`.

## Architecture plan

{plan}

## Hard requirements

- Write files into the CURRENT working directory.
- The entry point MUST be `index.html` at the root.
- Keep the implementation small and robust. Prefer one `index.html` with embedded CSS/JS, or at most `index.html`, `style.css`, and `script.js`.
- Render a desktop element whose id/class contains `desktop`.
- Render a taskbar element whose id/class contains `taskbar`.
- Render at least three launchable app icons using `.desktop-icon` and/or `data-app`.
- Clicking each icon must create/show a visible `.window` or `.os-window` element.
- Implement exactly these apps:
  - Notes: textarea persisted to localStorage.
  - Calculator: basic arithmetic.
  - Todo: add, complete, delete todos persisted to localStorage.
- Include a title bar and close button for each window.
- Avoid `type="module"`; use normal `<script>` so it works over `file://`.
- Do not spend time on advanced features. No games, no virtual file system, no complex window manager.

When the app is complete and functional, reply with exactly: BUILD COMPLETE
