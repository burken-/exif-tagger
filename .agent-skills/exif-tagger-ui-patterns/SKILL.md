---
name: exif-tagger-ui-patterns
description: Design system guidelines, color tokens, badge styling, dark mode toggle strategy, and custom hooks conventions for the EXIF Tagger React web app.
---

# EXIF Tagger UI Patterns & Design System

This skill provides comprehensive UI design patterns, color tokens, badge styling, dark mode configuration, component layout guidelines, and custom hook conventions for the EXIF Tagger React frontend.

## 1. Design Tokens & Color System

The application uses Tailwind CSS paired with CSS variables mapped to dark/light theme roots.

### Theme Strategy
- **Dark Mode (Default)**: Deep slate theme built for photo editing and long viewing sessions.
  - Page Background: `bg-slate-950` (`#020617`)
  - Card / Panel Background: `bg-slate-900` (`#0f172a`)
  - Border: `border-slate-800` (`#1e293b`)
  - Secondary Hover: `hover:bg-slate-800`
  - Text Primary: `text-slate-100` (`#f8fafc`)
  - Text Muted: `text-slate-400` (`#94a3b8`)
- **Light Mode**: Clean, high-contrast Slate theme.
  - Page Background: `bg-slate-50` (`#f8fafc`)
  - Card / Panel Background: `bg-white` (`#ffffff`)
  - Border: `border-slate-200` (`#e2e8f0`)
  - Secondary Hover: `hover:bg-slate-100`
  - Text Primary: `text-slate-900` (`#0f172a`)
  - Text Muted: `text-slate-500` (`#64748b`)

### Accent Colors & Status Tokens
- **Primary / Brand Accent**: Indigo / Blue (`indigo-600` dark / `indigo-500` light)
  - Interactive buttons, tab active indicators, focus rings.
- **Success / Completed**: Emerald (`emerald-600` / `emerald-500`)
  - Idle state badges, successful API responses, completion status.
- **Warning / Running**: Amber (`amber-600` / `amber-500`)
  - Processing running state, warning toasts, pending actions.
- **Danger / Error**: Red / Rose (`rose-600` / `red-500`)
  - Stop processing button, delete tag actions, error badges.

---

## 2. Shadcn UI Primitives & Styling Utility

Components are located in `src/components/ui/` and leverage the `cn()` utility function:

```typescript
import { ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

### Component Rules
- Always use the `cn(...)` utility when merging custom or conditional className props into UI primitives.
- Prefer Radix UI primitives as underlying headless engines for accessible dialogs, switches, and dropdowns.
- Avoid inline style attributes; use Tailwind classes exclusively.

---

## 3. Badge & Tag Styling Guidelines

Tags and badges are central to EXIF Tagger. They display EXIF metadata, AI-generated tags, and filtering states.

### Badge Specifications
- **Pill Shape**: Always use `rounded-full` for tags and badges.
- **Typography & Padding**: `px-2.5 py-0.5 text-xs font-medium inline-flex items-center gap-1`.
- **Variants**:
  - **Default Tag Badge**: `bg-slate-800 text-slate-200 border border-slate-700 hover:bg-slate-700 dark:bg-slate-800`
  - **Active Filter Tag**: `bg-indigo-600 text-white dark:bg-indigo-600 border border-indigo-500` with Lucide `X` dismiss icon (`w-3 h-3 hover:text-indigo-200 cursor-pointer`).
  - **Status Indicator Badges**:
    - *Idle*: `bg-emerald-500/10 text-emerald-400 border border-emerald-500/20`
    - *Running*: `bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse`
    - *Completed*: `bg-blue-500/10 text-blue-400 border border-blue-500/20`

---

## 4. Dark Mode Toggle Strategy

Dark mode is managed globally via `ThemeContext.tsx`.

### Key Requirements:
1. Default to `'dark'` mode.
2. Store theme preference in `localStorage` under key `'exif-tagger-theme'`.
3. Apply `.dark` class to `document.documentElement` (`<html>` element).
4. Provide a `useTheme()` custom hook:
   ```typescript
   const { theme, setTheme, toggleTheme } = useTheme();
   ```
5. Use Shadcn `Switch` component in the application `Header.tsx` displaying `Sun` and `Moon` Lucide icons.

---

## 5. State Management & Custom Hooks Conventions

Core business logic is cleanly separated into specialized custom React hooks in `src/hooks/`.

### Custom Hook Patterns:
- **`useGallery.ts`**:
  - Manages image catalog, tag filtering, pagination (`page`, `pageSize`, `totalPages`), image selections (`selectedImageIds`), breadcrumb navigation (`currentFolder`), search query, and URL hash synchronization (`#gallery?folder=...`).
- **`useProcessing.ts`**:
  - Manages session state (`isProcessing`, `progress`, `logs`), polling `/api/status`, start/stop processing operations, and auto-scrolling log console logic.
- **`useConfig.ts`**:
  - Manages server configuration settings (`rootDirectory`, `model`, `apiBaseUrl`, prompt parameters), fetching `/api/config` and posting updates.
- **`useSchedule.ts`**:
  - Manages cron schedule jobs (`schedules`), manual job execution triggers, schedule deletion, and schedule creation.

### Data Fetching Conventions:
- Handle loading and error states explicitly in all hooks.
- Use `useEffect` with appropriate cleanup functions for polling intervals or web socket/event stream subscriptions.

---

## 6. Layout & Responsive Grid Standards

### Container Standard
All tab views are wrapped within the main application container:
```tsx
<main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
  {/* Tab views */}
</main>
```

### Grid Breakpoints
- **Image Grid**: `grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4`
- **Dashboard Cards**: `grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6`

---

## 7. Typography & Iconography

- **UI Font**: Inter / sans-serif (`font-sans`).
- **Console / Code Font**: Fira Code / monospace (`font-mono`) for log viewers and path displays.
- **Icons**: Lucide React (`lucide-react`). Standard icon sizes: `w-4 h-4` (inline/buttons), `w-5 h-5` (navigation/headers).
