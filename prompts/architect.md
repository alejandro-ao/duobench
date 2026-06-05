You are an expert front-end architect and OS designer. I want you to design a complete, desktop-like WebOS that runs entirely in a single browser tab using vanilla JavaScript, HTML, and CSS.

## Core Requirements

1. **Window Manager**
   - Draggable, resizable, minimizable, maximizable, closable windows
   - Z-index management (click to focus, bring to front)
   - Window title bar with icon, title, and control buttons
   - Snap-to-edge behavior (optional but nice)

2. **Taskbar**
   - Bottom-aligned taskbar like Windows/macOS
   - Start menu / app launcher button
   - Open window previews / task switching
   - System tray with clock and notifications
   - Quick-launch pins

3. **Built-in Apps** (each runs inside a window)
   - **File Manager**: tree view, file listing, create/rename/delete files and folders, breadcrumbs
   - **Calculator**: standard + scientific modes, calculation history
   - **Reminders**: create, edit, delete reminders with due dates, localStorage persistence
   - **Text Editor**: simple notepad with open/save (to the virtual file system)
   - **Settings**: themes (light/dark/custom), wallpaper selector, system preferences

4. **Games** (each runs inside a window)
   - **Snake**: classic snake with score, high score persistence, increasing speed
   - **Tetris**: full tetris with hold piece, next piece preview, line clearing, scoring, levels
   - Bonus: **Minesweeper** or **2048** if the architecture supports easy addition

5. **App System**
   - App registry: each app is a self-contained module with metadata (name, icon, factory function)
   - Apps can be launched from Start Menu, desktop icons, or taskbar
   - Clean API for adding new apps without modifying core OS code

6. **Virtual File System**
   - In-memory file system with folders and files
   - Persist to localStorage (serialize/deserialize)
   - Used by File Manager and Text Editor

7. **Design & UX**
   - Modern, clean aesthetic (think Windows 11 or macOS)
   - Smooth animations for window open/close/minimize
   - Responsive: works on different screen sizes
   - Wallpaper support with a few built-in options
   - Context menus (right-click on desktop, files, taskbar)

## Deliverables

Provide:
1. **Architecture Overview**: high-level component diagram and data flow
2. **File Structure**: recommended folder/file organization
3. **Core Classes/Modules**: WindowManager, Taskbar, AppRegistry, FileSystem, etc. with key methods
4. **App Interface**: what each app must implement to integrate with the OS
5. **CSS Architecture**: how theming works, CSS variables, layout approach
6. **Game Loop Design**: how games integrate without blocking the OS event loop
7. **State Management**: how global state is handled (window states, file system, settings)
8. **Implementation Order**: recommended sequence to build this incrementally

Be specific. Include code sketches for the core classes and interfaces. The goal is that a skilled developer could take your plan and implement this in a few hours.
