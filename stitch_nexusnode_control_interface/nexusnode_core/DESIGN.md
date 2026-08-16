---
name: NexusNode Core
colors:
  surface: '#0d1516'
  surface-dim: '#0d1516'
  surface-bright: '#333a3c'
  surface-container-lowest: '#080f11'
  surface-container-low: '#151d1e'
  surface-container: '#192122'
  surface-container-high: '#242b2d'
  surface-container-highest: '#2e3638'
  on-surface: '#dce4e5'
  on-surface-variant: '#bac9cc'
  inverse-surface: '#dce4e5'
  inverse-on-surface: '#2a3233'
  outline: '#849396'
  outline-variant: '#3b494c'
  surface-tint: '#00daf3'
  primary: '#c3f5ff'
  on-primary: '#00363d'
  primary-container: '#00e5ff'
  on-primary-container: '#00626e'
  inverse-primary: '#006875'
  secondary: '#dab9ff'
  on-secondary: '#460283'
  secondary-container: '#602b9d'
  on-secondary-container: '#cfa7ff'
  tertiary: '#ffeac0'
  on-tertiary: '#3e2e00'
  tertiary-container: '#fec931'
  on-tertiary-container: '#6f5500'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#9cf0ff'
  primary-fixed-dim: '#00daf3'
  on-primary-fixed: '#001f24'
  on-primary-fixed-variant: '#004f58'
  secondary-fixed: '#eedbff'
  secondary-fixed-dim: '#dab9ff'
  on-secondary-fixed: '#2a0053'
  on-secondary-fixed-variant: '#5e289b'
  tertiary-fixed: '#ffdf96'
  tertiary-fixed-dim: '#f3bf26'
  on-tertiary-fixed: '#251a00'
  on-tertiary-fixed-variant: '#594400'
  background: '#0d1516'
  on-background: '#dce4e5'
  surface-variant: '#2e3638'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  data-lg:
    fontFamily: JetBrains Mono
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 20px
  data-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
  data-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.02em
  label-caps:
    fontFamily: Inter
    fontSize: 10px
    fontWeight: '700'
    lineHeight: 12px
    letterSpacing: 0.06em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  container-padding: 16px
  stack-gap: 8px
  element-gap: 4px
  section-margin: 24px
---

## Brand & Style
The design system is engineered for high-performance server management, blending the raw technical utility of a network appliance with the refined precision of a premium mobile interface. It prioritizes information density and instant legibility over decorative elements.

The aesthetic follows a **Modern Technical** approach:
- **High-Density Utility:** Maximizing screen real estate to provide a comprehensive overview of system health without excessive scrolling.
- **OLED Optimized:** Utilizing true black backgrounds to reduce power consumption and increase the perceived contrast of data visualizations.
- **Functional Precision:** Every line, border, and color serves a diagnostic purpose, evoking the feeling of a hardware rack mount display.
- **No-Fuss Professionalism:** Avoiding trends like glassmorphism or soft neomorphism in favor of hard-edged surfaces and clear containment.

## Colors
This design system utilizes a high-contrast dark palette designed for technical environments.

- **Foundational Neutrals:** True black (#000000) serves as the primary canvas. Surface levels (Graphite and Dark Grey) are used to create structural depth and separate logic blocks.
- **Accent Logic:**
    - **Cyan (Primary):** Reserved for network activity, active connections, and primary interaction points.
    - **Purple (AI/Ollama):** Specifically designated for local LLM processing units and AI-specific metrics.
- **Semantic Feedback:** Success, Warning, and Error colors follow standard hardware LED conventions. These should be used with high saturation against the dark background to ensure immediate recognition of system states.
- **Borders:** Used instead of shadows to define containers, maintaining a flat, architectural feel.

## Typography
The typography strategy employs a dual-font approach to distinguish between UI orchestration and technical data.

- **Inter (Interface):** Used for navigation, headings, and general descriptions. It provides the necessary readability for a professional SaaS environment.
- **JetBrains Mono (Data):** Used for all dynamic values, IP addresses, logs, and metrics. The monospaced nature ensures that fluctuating values (like CPU % or bitrates) do not cause layout shifts.
- **Compactness:** Leading is intentionally tight to support the high-density layout requirements of a server dashboard.
- **Hierarchy:** Strong contrast in weights is preferred over large size differentials to keep the mobile interface compact.

## Layout & Spacing
The layout uses a **Fluid Technical Grid** with a 4px base unit. 

- **Density:** Space is treated as a premium resource. Padding inside cards is minimal (usually 12px or 16px) to maximize the visible data area.
- **Vertical Rhythm:** Elements are stacked primarily in a single column for mobile, using consistent 8px gaps between related items.
- **Sticky Navigation:** The primary navigation and "Global Status" bar (showing Uptime/Load) remain fixed at the bottom and top respectively, ensuring critical system health is always visible.
- **Horizontal Metering:** Use full-width bars for resource distribution (RAM/Disk) to allow for quick scanning.

## Elevation & Depth
This design system rejects traditional shadows and blurs in favor of **Tonal Layering and Borders**.

- **Level 0 (Base):** #000000. Used for the main application background.
- **Level 1 (Surfaces):** #121212. Used for secondary containers, card backgrounds, and list items.
- **Level 2 (Active/Floating):** #1C1C1C. Used for headers, input fields, and elements that require immediate user focus.
- **Structural Outlines:** All containers must have a 1px solid border (#2C2C2C). For "Active" or "Selected" states, the border color should shift to the Primary Cyan or the relevant status color.
- **Depth through Contrast:** Visual hierarchy is achieved by the contrast between the absolute black background and the graphite-colored containers.

## Shapes
Shapes are "Soft" but lean toward industrial. 

- **Standard Radius:** 4px (rounded-md) for most cards, buttons, and input fields.
- **Small Radius:** 2px (rounded-sm) for status chips and small technical labels.
- **No Pill Shapes:** Avoid fully rounded pill shapes as they contradict the rigid, technical nature of server hardware. Buttons and chips should remain rectangular with slight softening.

## Components
- **Horizontal Meters:** Used for CPU, RAM, and Storage. These consist of a background track (#2C2C2C) and a filled indicator using the status colors (Green, Amber, Red). Use a height of 8px for standard meters.
- **Status Chips:** Small, rectangular containers with a subtle background tint and a high-contrast dot or text label. Used for "Online," "Idle," or "Running."
- **Expandable Technical Sections:** Use a "Chevron-Right" icon that rotates 90 degrees. Content inside should be presented in a monospaced font on a slightly darker sub-surface.
- **Action Buttons:** Flat surfaces with the Primary Cyan border. For destructive actions (Stop/Delete), use a subtle Red border. No gradients.
- **Input Fields:** Dark grey backgrounds (#1C1C1C) with #2C2C2C borders. Upon focus, the border transitions to Primary Cyan.
- **Mini-Charts:** Sparklines should be used within cards to show 24h trends. These lines should be 1.5px thick and use the Primary Cyan or AI Purple depending on the data source.