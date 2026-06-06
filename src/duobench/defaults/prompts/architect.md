You are an expert front-end architect. Design a SMALL browser desktop app called **MiniDesk** that can be implemented quickly in vanilla HTML, CSS, and JavaScript.

The goal is a lightweight benchmark task, not a giant operating system. Keep the plan concise and implementation-friendly.

## Product Requirements

Build a single-page desktop-like interface that runs directly from `index.html` using `file://` with no server, build step, frameworks, modules, CDNs, or external assets.

Required UI:

1. **Desktop shell**
   - A visible desktop area with id or class containing `desktop`.
   - A visible bottom taskbar with id or class containing `taskbar`.
   - A clock in the taskbar.
   - A polished but simple visual style.

2. **Three launchable apps**
   - At least three visible desktop icons using `.desktop-icon` and/or `data-app` attributes.
   - Clicking each icon opens a visible window element using class `.window` or `.os-window`.
   - Windows must have a title bar and close button.
   - Windows should be draggable if practical, but dragging is optional.

3. **Required apps**
   - **Notes**: a textarea; text persists in `localStorage`.
   - **Calculator**: buttons or inputs for basic arithmetic; at minimum supports add/subtract/multiply/divide through a simple expression field or keypad.
   - **Todo**: add todos, mark complete, delete todos; persists in `localStorage`.

4. **Quality expectations**
   - All logic can live in one `index.html`, or in `index.html` plus a small `style.css` and `script.js`.
   - Prefer simple, robust code over complex architecture.
   - No ES modules. Use plain script tags so the app works over `file://`.
   - No external images; use CSS gradients and emoji/icons if desired.

## Deliverable — concise architecture plan

Write a compact implementation plan for the developer. Do NOT write full working code.

Include:

1. Recommended file structure.
2. DOM structure and important CSS classes/ids.
3. JavaScript state shape.
4. Functions/components to implement.
5. App behavior for Notes, Calculator, and Todo.
6. Acceptance criteria.

Keep the plan under 900 words. The implementer should be able to finish in under 10 minutes.
