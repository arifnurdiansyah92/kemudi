---
name: Kemudi
description: Delivery control for IT vendors working under contract; a quiet work surface steered from a deep-ink helm.
colors:
  helm-ink: "oklch(0.22 0.045 255)"
  helm-ink-raised: "oklch(0.285 0.05 255)"
  helm-text: "oklch(0.86 0.02 250)"
  brass: "oklch(0.62 0.12 75)"
  brass-bright: "oklch(0.76 0.12 78)"
  deep-navy: "oklch(0.33 0.07 252)"
  harbour-teal: "oklch(0.52 0.09 185)"
  signal-red: "oklch(0.56 0.2 27)"
  chart-violet: "oklch(0.6 0.08 300)"
  mist: "oklch(0.975 0.004 250)"
  paper: "oklch(1 0 0)"
  slate-ink: "oklch(0.24 0.04 258)"
  slate-muted: "oklch(0.5 0.03 255)"
  tint: "oklch(0.945 0.008 250)"
  hairline: "oklch(0.905 0.01 250)"
  input-line: "oklch(0.88 0.012 250)"
  night-surface: "oklch(0.17 0.03 255)"
  night-card: "oklch(0.205 0.032 255)"
typography:
  headline:
    fontFamily: "Schibsted Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.33
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Schibsted Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "Schibsted Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.43
  label:
    fontFamily: "Schibsted Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.33
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "12px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "6": "24px"
  "8": "32px"
components:
  button-primary:
    backgroundColor: "{colors.deep-navy}"
    textColor: "{colors.mist}"
    rounded: "{rounded.md}"
    typography: "{typography.body}"
    height: "36px"
    padding: "8px 16px"
  button-outline:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.md}"
    height: "36px"
    padding: "8px 16px"
  button-ghost:
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.md}"
    height: "36px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.md}"
    height: "36px"
    padding: "4px 12px"
  nav-item:
    textColor: "{colors.helm-text}"
    rounded: "{rounded.md}"
    height: "32px"
  nav-item-active:
    backgroundColor: "{colors.helm-ink-raised}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.xl}"
  status-pill:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.md}"
    typography: "{typography.label}"
---

# Design System: Kemudi

## Overview

**Creative North Star: "The Helm"**

Kemudi is the helm of a delivery project. The sidebar is the wheelhouse: deep sea ink in both themes, with a single brass marker showing where you are. Everything to its right is the chart table, a quiet, cool work surface where the data (stories, sprints, statuses, people) does the talking. The brand lives in the helm and a few brass details; the work surface stays out of the way.

The surface is dense and operational. People scan long lists, drag cards and compare numbers all day, so rows are compact (about 45px), type sits mostly at 14px and 12px, and color is reserved for meaning: status dots, a red for blocked or destructive, teal for done and success. Brass is rare by design; it marks you (your place, your focus, your watch, your unread), nothing decorative.

Both languages share one layout. Indonesian labels run longer than English, so components grow with their text instead of truncating fixed-width labels.

**Key Characteristics:**

- Deep-ink sidebar (the helm) in light and dark themes alike; the work surface switches.
- Brass marks you: your place, your focus, your watches and unread notifications.
- Cool blue-grey neutrals with a slight 250° hue; no warm greys.
- Flat surfaces separated by hairlines, with a light shadow only on raised, movable or floating things.
- Compact, scannable rows; status colors come from each project's own configuration.

## Colors

A cool navy-and-mist palette, anchored by an ink helm and a single brass accent.

### Primary

- **Deep Navy** (deep-navy): primary buttons, links, the selected segment in toggles, chart series 1. In dark mode the primary role passes to Brass Bright, so the main action reads warm on the night surface.
- **Brass** (brass) / **Brass Bright** (brass-bright): the active nav marker (a 3px bar on the item's leading edge), focus rings, the logo mark, your own state (watching, voted, unread). Never fills large areas.

### Secondary

- **Harbour Teal** (harbour-teal): success, done and closed states, chart series 2.

### Tertiary

- **Signal Red** (signal-red): destructive actions, errors, blocked items and the issue type label.
- **Chart Violet** (chart-violet): chart series 4 only.

### Neutral

- **Helm Ink** (helm-ink): sidebar background. Helm Ink Raised (helm-ink-raised) is the active or hovered nav item; Helm Text (helm-text) is nav text.
- **Mist** (mist): the app background behind cards and lists.
- **Paper** (paper): cards, list containers, popovers, inputs.
- **Slate Ink** (slate-ink): body text and headings. **Slate Muted** (slate-muted): secondary text, metadata, refs (#18), placeholders.
- **Tint** (tint): secondary buttons, tag chips, column backgrounds.
- **Hairline** (hairline): borders and row dividers. **Input Line** (input-line): input strokes, slightly darker than Hairline.
- **Night Surface** (night-surface) / **Night Card** (night-card): the dark theme's background and card. Dark borders are white at 9% opacity.

### Named Rules

**The Brass Means You Rule.** Brass marks you: where you are (the active nav bar, keyboard focus) and what is yours (things you watch or voted for, your unread notifications, the forecast line in your backlog). It is never decoration, a status color or a layout fill. The one sanctioned fill is the dark theme's primary button, where Brass Bright takes the primary role so the main action reads warm on the night surface.

**The Meaning-Only Color Rule.** Outside the helm, color carries state: a status, a type, success or danger. A colored element with no state behind it is a bug.

**The Server Owns Status Color Rule.** Status, type, priority and severity colors come from each project's settings in kemudi-back. The UI shows them as a dot or chip and never re-themes them.

## Typography

**Display Font:** none; the app has no display tier.
**Body Font:** Schibsted Grotesk Variable (bundled through fontsource; fallback ui-sans-serif, system-ui). Settings → Appearance can switch to the system font.

**Character:** a sturdy, slightly condensed news grotesk. Firm at 600 for headings, neutral and legible at 14px for long lists.

### Hierarchy

- **Headline** (600, 1.5rem, 1.33): page titles: "Backlog", "Hello, Web Developer".
- **Title** (600, 1rem, 1.5): section headings ("Working on", "Open sprints"), sheet and dialog titles, sprint names.
- **Body** (400, 0.875rem, 1.43): list rows, form fields, buttons, descriptions. Rich text (descriptions, comments, wiki) uses line-height 1.6.
- **Label** (500, 0.75rem, 1.33): metadata, counts, chips, status pills, refs, sidebar group labels.

### Named Rules

**The Two Sizes Rule.** Working UI lives at 14px and 12px; size steps above that are for page and section titles only. Use weight and muted color for hierarchy inside a list, not size.

## Layout

A fixed helm on the left (256px, collapsible to icons; an off-canvas sheet on mobile) and an inset work surface with rounded corners on the right. Pages open with a header bar (sidebar toggle, breadcrumb, Jump to… search, notifications, theme), then a page title block, then content on a 4px grid, mostly 16px and 24px gaps and 32px page gutters.

The backlog is a two-column layout: the story list (flexible) and open sprints (about 384px). Kanban scrolls horizontally with fixed-width columns (about 280px) and offers Compact, Standard and Detailed card density. The item sheet slides in from the right over any project page (`?ref=`).

Content containers use container queries (`@container/content`), so panels respond to the space the sidebar leaves.

## Elevation & Depth

Mostly flat, built from tonal layers: Mist background, Paper containers, Tint inside them. Hairlines do the separating. Shadows are small and structural: `shadow-xs` on buttons and inputs, a soft `shadow-sm` on kanban cards and sprint panels, and `shadow-lg` only on floating layers (popovers, dropdowns, sheets, dialogs, cards being dragged).

### Named Rules

**The Lift Means Movable Rule.** A shadow larger than `xs` says "this floats or can be moved". Static containers stay flat with a hairline.

## Shapes

Gently rounded: 6px on controls (buttons, inputs, chips, pills, nav items), 8px on popovers and list containers, 12px on cards and the inset work surface. Avatars are circles; project marks in lists are 6px-rounded squares with a single initial. The active nav item's 3px brass bar is the one sharp-edged signature.

## Components

### Buttons

- **Shape:** gently rounded (6px), 36px tall (32px small, 40px large).
- **Primary:** Deep Navy fill with Mist text (Brass Bright with ink text in dark mode), 14px medium. One per view, for the main action ("New story").
- **Outline:** Paper fill with a hairline, for secondary actions beside a primary ("Add several", "New sprint").
- **Ghost:** no fill until hover (Tint), for toolbar and row actions (the ⋯ menus).
- **Focus:** a 3px ring in Brass at 50% opacity.

### Chips and status pills

- **Status pill:** Paper with a hairline, a 6px colored dot from the project's status color, a 12px medium label and a chevron when editable.
- **Tag chip:** Tint background, Slate Muted 12px text, with a colored dot when the tag has a color.

### Cards and containers

- **List container:** Paper, hairline border, 8px radius, rows split by hairlines, about 45px per row.
- **Kanban card:** Paper, 8px radius, `shadow-xs`, title in 14px, then tags and ref in 12px muted.
- **Sprint panel:** Paper, 12px radius, a header with name, date range and points, then compact story rows.

### Inputs and fields

- **Style:** Paper fill, an Input Line stroke, 6px radius, 36px tall, `shadow-xs`.
- **Focus:** a Brass ring (3px at 50%).
- **Error:** a Signal Red border and ring.
- **Filter buttons:** outline buttons with a filter icon, sitting in one row with the search field.

### Navigation

- **Helm (sidebar):** Helm Ink with Helm Text items at 14px. Group labels (Workspace, the project's name, You) in 12px muted. Hover and active use Helm Ink Raised. The active item is semibold, white, with a 3px Brass bar on its leading edge.
- **Header:** a breadcrumb (project > page) and the Jump to… command search (⌘K) on the right.

### Item sheet (signature component)

A right-side sheet showing any story, task, issue or epic. The subject is editable in place, fields sit in a property column (status, assignees, points, due date, tags, custom fields), and description, tasks, attachments, comments and history follow below.

## Do's and Don'ts

### Do:

- **Do** keep the sidebar Helm Ink in both themes and mark the active item with the 3px Brass bar.
- **Do** get text sizes from the 14px / 12px pair and build hierarchy with weight and Slate Muted.
- **Do** let buttons, tabs, pills and table headers grow with their label; Indonesian strings run 20–40% longer.
- **Do** render project-defined status, type, priority and severity colors as dots or chips, exactly as configured.
- **Do** keep row height compact (about 45px) in lists, and use the kanban density switch rather than inventing new card layouts.

### Don't:

- **Don't** use Brass for decoration, status or anything that isn't about the viewer.
- **Don't** add warm greys or pure neutral greys; neutrals carry the 250° cool hue.
- **Don't** give static containers a drop shadow; shadows mean floating or movable.
- **Don't** truncate action labels or fix button widths to fit English text.
- **Don't** add decorative color, gradients or illustrations to working screens.
