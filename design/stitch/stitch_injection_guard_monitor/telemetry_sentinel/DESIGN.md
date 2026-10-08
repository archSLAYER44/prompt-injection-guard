---
name: Telemetry Sentinel
colors:
  surface: '#121318'
  surface-dim: '#121318'
  surface-bright: '#38393e'
  surface-container-lowest: '#0d0e13'
  surface-container-low: '#1a1b20'
  surface-container: '#1e1f25'
  surface-container-high: '#292a2f'
  surface-container-highest: '#34343a'
  on-surface: '#e3e1e9'
  on-surface-variant: '#c2c6d4'
  inverse-surface: '#e3e1e9'
  inverse-on-surface: '#2f3036'
  outline: '#8c919d'
  outline-variant: '#424752'
  surface-tint: '#aac7ff'
  primary: '#aac7ff'
  on-primary: '#002f64'
  primary-container: '#5794f2'
  on-primary-container: '#002c5e'
  inverse-primary: '#045db8'
  secondary: '#8bd980'
  on-secondary: '#003a05'
  secondary-container: '#01560c'
  on-secondary-container: '#7eca73'
  tertiary: '#ffb3b4'
  on-tertiary: '#680017'
  tertiary-container: '#ff5a6a'
  on-tertiary-container: '#610015'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#d6e3ff'
  primary-fixed-dim: '#aac7ff'
  on-primary-fixed: '#001b3e'
  on-primary-fixed-variant: '#00458d'
  secondary-fixed: '#a6f699'
  secondary-fixed-dim: '#8bd980'
  on-secondary-fixed: '#002202'
  on-secondary-fixed-variant: '#00530a'
  tertiary-fixed: '#ffdada'
  tertiary-fixed-dim: '#ffb3b4'
  on-tertiary-fixed: '#40000b'
  on-tertiary-fixed-variant: '#920024'
  background: '#121318'
  on-background: '#e3e1e9'
  surface-variant: '#34343a'
typography:
  headline-xl:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Geist
    fontSize: 15px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: -0.01em
  panel-title:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0em
  body-default:
    fontFamily: Geist
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: 0em
  body-sm:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  mono-data:
    fontFamily: monospace
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  mono-metric:
    fontFamily: monospace
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 26px
    letterSpacing: -0.02em
  badge-label:
    fontFamily: Geist
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.75rem
  gutter-mobile: 0.5rem
  margin: 1rem
  margin-mobile: 0.75rem
  space-2xs: 0.125rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.875rem
  space-lg: 1rem
  space-xl: 1.5rem
  space-2xl: 2rem
---

## Brand & Style

This design system establishes an ultra-precise, developer-centric telemetry interface engineered for real-time LLM prompt injection security operations. Rooted in the visual tradition of high-density observability dashboards, the style emphasizes analytical rigor, spatial economy, and tactical situational awareness.

The aesthetic fuses modern telemetry tooling with disciplined micro-density: razor-sharp geometry, matte dark-matter backdrops, deliberate panel separation, and high-legibility typographic hierarchies. Rather than decorative elements or gratuitous dimensionality, every pixel exists to convey stream status, security thresholds, latency percentiles, and threat vectors without cognitive friction.

Interfaces built with this system project absolute reliability, technical composure, and surgical precision under incident response conditions.

## Colors

The palette operates within a disciplined dark tonal structure engineered for high-contrast telemetry legibility across prolonged operational shifts.

- **Background Canvas (`#111217`)**: Deep neutral void, absorbing visual noise and serving as the foundational floor for all layout grids.
- **Surface / Panel (`#181b1f`)**: Crisp matte container tier providing distinct contrast against the canvas while preventing visual fatigue.
- **Border (`#2c3235`)**: Structural line work delineating dense telemetry partitions without commanding visual dominance. Elevated or interactive borders step up to `#3b4247`.
- **Text Primary (`#d8d9da`)**: High-contrast, optical-grade primary foreground text ensuring maximum readability against dark panels.
- **Text Muted (`#9fa3aa`)**: Secondary hierarchy color dedicated to metric descriptions, column headers, timestamps, and panel titles.
- **Status Tiers**: Semantic telemetry values must maintain instant legibility:
  - Allowed / Normal: `#73BF69`
  - Blocked / Threat Vector: `#F2495C`
  - Warning / Near Threshold: `#FADE2A`
  - Primary / Interactive Focus: `#5794F2`

Status signals must never be communicated through color alone; every threat indicator requires an adjacent vector icon, score delta, or explicit semantic badge.

## Typography

Typographic hierarchy prioritizes tabular structure, immediate scannability, and high density. The system pairs `Geist` for structured interface elements, navigation, and body copy with system monospaced families for deterministic data visualization.

- **Panel Titles**: Rendered at `13px` with a `500` weight in sentence case using muted `#9fa3aa`. This preserves content prominence inside the panel body while retaining clear analytical boundaries.
- **General Body**: Calibrated to a base of `15px` (`400` weight) in high-contrast `#d8d9da` for logs, tooltips, dialogue blocks, and inspector readouts.
- **Telemetry & Monospace**: Token counts, prompt hashes, detection confidence scores, model latencies, and vector coordinates strictly utilize monospaced rendering. KPI callouts leverage `mono-metric` (`22px / 600`) to guarantee tabular number alignment across live refresh intervals.
- **Labels & Micro-data**: Column sorting tags, protocol indicators, and table headers scale down to `11px` to `12px` with expanded letter spacing for effortless micro-scanning.

## Layout & Spacing

Layout geometry follows an intensive 24-column or 12-column analytical grid modeled on high-throughput observability dashboards. Space is treated as a finite resource: vertical and horizontal gaps are tightened to expose critical operational indicators simultaneously above the fold.

- **Panel Canvas**: Standard panel padding is locked at `14px` (`space-md`), balancing tight data bounds with breathing room for chart rendering and stream inspection.
- **Gutters & Separation**: Dashboard panels sit with uniform `12px` (`0.75rem`) gutters between adjacent metrics.
- **Navigation & Controls Bar**: The top horizontal header enforces a fixed `48px` height with `16px` outer horizontal margins, featuring uninterrupted tab transitions.
- **Responsive Dynamics**:
  - **Desktop (≥ 1280px)**: Multi-column grid showcasing live chat streams, guard inspector trees, and real-time histogram panels side by side.
  - **Tablet (768px - 1279px)**: Columns collapse into dynamic dual-pane layouts with sliding inspector sheets.
  - **Mobile (< 768px)**: Strict vertical stacking where primary telemetry graphs collapse into collapsible accordion panels and tabbed navigation shifts to a compact horizontal rail.

## Elevation & Depth

Visual hierarchy does not rely on heavy drop shadows or dramatic blurs. Depth is conveyed strictly via tonal surface tiers and razor-sharp 1px low-contrast line boundaries.

- **Level 0 (Canvas Base)**: `#111217` — The foundational backdrop for the entire viewport.
- **Level 1 (Telemetry Panels & Tables)**: `#181b1f` bordered by `1px solid #2c3235`. Zero blur shadow. Visual boundary is purely tactile via the color shift and subtle perimeter line.
- **Level 2 (Overlays, Dropdowns, Flyouts)**: `#20242a` bordered by `1px solid #3b4247` paired with an ambient, disciplined shadow: `box-shadow: 0 4px 16px rgba(0, 0, 0, 0.45)`.
- **Level 3 (Modal Alerts & Threat Interceptions)**: `#181b1f` elevated with `box-shadow: 0 12px 32px rgba(0, 0, 0, 0.65)` with a high-contrast perimeter highlight (`1px solid #5794F2` or `#F2495C` depending on threat severity).

## Shapes

The shape vocabulary emphasizes structural efficiency, minimal deflection, and industrial discipline.

- **Corners (`roundedness: 1`)**: All standard monitoring panels, cards, data tables, and input fields utilize an exact `4px` (`0.25rem`) corner radius. This delivers subtle softening without compromising the structured grid aesthetic.
- **Pills and Badges**: Status chips and indicator pills use `2px` or `4px` micro-radii to maintain tight perimeter cohesion with neighboring telemetry blocks. Pill shapes are intentionally avoided for data metrics to keep scanlines uniform.
- **Form Controls & Actionables**: Action buttons, search fields, and filter selects match the foundational `4px` radius for uniform spatial rhythm.

## Components

### 1. Navigation Bar
- Fixed top navigation header, `48px` height, `#181b1f` background with a `1px solid #2c3235` bottom border.
- Horizontal tab sequence: `Chat`, `Guard inspector`, `Monitoring`, `History`, `About`.
- Inactive tabs: `#9fa3aa`, `13px`, medium weight, interactive hover transition to `#d8d9da`.
- Active tab: `#5794F2` text with an explicit `2px` solid `#5794F2` bottom accent line and subtle `#5794F210` background highlight.

### 2. Telemetry Panels
- Container: `#181b1f`, `4px` border radius, `1px solid #2c3235`, `14px` uniform padding.
- Panel Header: Dedicated flex row with title at `13px`, medium weight, sentence case, in `#9fa3aa`. Right-aligned micro-actions (time picker, refresh cadence, expand icon, filter pills).
- Content Area: Houses dense data tables, timeseries canvases, score distributions, or payload hex dumps.

### 3. Threat Status Indicators & Badges
- Strict rule: Status displays must never rely solely on color. Every indicator unites an icon, a label, and a color-coded perimeter/fill.
- **Allowed**: `Check` icon, `#73BF69` text, `#73BF6915` background, `1px solid #73BF6940` border.
- **Blocked**: `Shield-Alert` icon, `#F2495C` text, `#F2495C15` background, `1px solid #F2495C40` border.
- **Near Threshold / Warning**: `Alert-Triangle` icon, `#FADE2A` text, `#FADE2A15` background, `1px solid #FADE2A40` border.
- Radius: `4px`. Micro padding: `2px 8px`. Font: `11px`, `500` weight, monospace value pairing.

### 4. Interactive Buttons
- **Primary Action**: `#5794F2` background, `#111217` font color for instant contrast, `4px` radius, `6px 14px` padding, `13px` font size, `500` weight. Hover: `#6ea5f7`. Active: `#4682e0`.
- **Secondary / Ghost**: `#181b1f` background, `1px solid #2c3235`, text `#d8d9da`. Hover: `#20242a`, border `#3b4247`.
- **Destructive**: `#F2495C15` background, `1px solid #F2495C40`, text `#F2495C`.

### 5. Inputs & Query Fields
- Background: `#111217`, `1px solid #2c3235`, `4px` radius, text `#d8d9da`, placeholder `#9fa3aa`.
- Focus state: `1px solid #5794F2` with subtle `box-shadow: 0 0 0 1px #5794F2`.
- Monospace variant used for prompt injection signature filters, regex matchers, and token stream inspectors.

### 6. Data Tables & Stream Lists
- Dense row height: `32px` to `36px`.
- Headers: `12px`, sentence case, `#9fa3aa`, border-bottom `1px solid #2c3235`.
- Rows: Alternating hover fill `#20242a40`, divider line `1px solid #2c323520`.
- Cells: Numerical values, token counts, latency latencies (e.g., `42ms`), and confidence vectors rendered in `mono-data`.