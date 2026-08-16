---
name: NexusNode
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353534'
  on-surface: '#e5e2e1'
  on-surface-variant: '#bac9cc'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#313030'
  outline: '#849396'
  outline-variant: '#3b494c'
  surface-tint: '#00daf3'
  primary: '#c3f5ff'
  on-primary: '#00363d'
  primary-container: '#00e5ff'
  on-primary-container: '#00626e'
  inverse-primary: '#006875'
  secondary: '#e4b5ff'
  on-secondary: '#4e0078'
  secondary-container: '#ab08ff'
  on-secondary-container: '#fef0ff'
  tertiary: '#efeceb'
  on-tertiary: '#303030'
  tertiary-container: '#d2d0cf'
  on-tertiary-container: '#5a5959'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#9cf0ff'
  primary-fixed-dim: '#00daf3'
  on-primary-fixed: '#001f24'
  on-primary-fixed-variant: '#004f58'
  secondary-fixed: '#f4d9ff'
  secondary-fixed-dim: '#e4b5ff'
  on-secondary-fixed: '#2f004b'
  on-secondary-fixed-variant: '#6f00a9'
  tertiary-fixed: '#e5e2e1'
  tertiary-fixed-dim: '#c8c6c5'
  on-tertiary-fixed: '#1b1b1c'
  on-tertiary-fixed-variant: '#474746'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353534'
  oled-black: '#000000'
  graphite-surface: '#121212'
  graphite-raised: '#1E1E1E'
  border-subtle: '#333333'
  status-healthy: '#00C853'
  status-warning: '#FFD600'
  status-critical: '#D50000'
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
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 24px
  stack-gap: 8px
  touch-target: 44px
---

## Brand & Style

The design system is a high-performance utility framework engineered for server management and network orchestration. It blends the raw technical aesthetic of a rack-mount appliance with the precision of a modern monitoring interface.

The aesthetic follows a **Modern Technical** approach:
- **OLED Optimized:** Leverages a true black foundation to maximize contrast and reduce power consumption on mobile displays.
- **Functional Precision:** Every visual element serves a diagnostic purpose. Decorative flourishes are rejected in favor of hard-edged surfaces and clear containment.
- **High-Density Utility:** Prioritizes information density, allowing operators to monitor complex system health at a glance without excessive scrolling.
- **Industrial Minimalist:** A "no-fuss" professional look that avoids trends like glassmorphism or neomorphism, focusing instead on 1px borders and tonal layering.

## Colors

The palette is strictly functional, utilizing high-contrast accents against a deep, multi-tiered dark background.

- **Foundational Neutrals:** OLED Black (#000000) is the base application canvas. Graphite levels (#121212 and #1E1E1E) provide structural depth for containers and raised surfaces.
- **System Accents:** 
  - **Cyan (Primary):** Dedicated to network activity, system orchestration, and primary interactive states.
  - **Purple (AI):** Strictly reserved for AI operations, LLM processing units, and specialized neural metrics.
- **Status Language:** Semantic colors (Green, Amber, Red) follow hardware LED conventions for healthy, warning, and critical states.
- **Borders:** A restrained 1px Graphite (#333333) border is used for containment, maintaining a flat architectural feel.

## Typography

This system employs a dual-font strategy to separate interface orchestration from raw technical data.

- **Inter:** The primary interface typeface. It is used for all navigational elements, headers, and descriptions to ensure maximum readability.
- **JetBrains Mono:** Reserved for all dynamic system values, IP addresses, logs, and technical metrics. The monospaced nature prevents layout shifts when numerical values fluctuate rapidly.
- **Hierarchy:** High contrast in font weights is preferred over large size differentials to maintain a compact, dense layout. 
- **Formatting:** Labels for system statuses or categories should use the `label-caps` style for an industrial, "tagged" appearance.

## Layout & Spacing

The layout is built on a 4px base unit, focusing on a **Fluid Technical Grid** that maximizes data density.

- **Desktop:** Features a compact top navigation bar and dense, multi-column information panels. Horizontal space is used for resource metering and expanded log views.
- **Mobile:** Implements a bottom-navigation architecture for ergonomic reachability. A 16px container padding is standard, with a minimum touch target of 44px for all interactive elements.
- **Density:** Padding inside cards is kept minimal (12px to 16px) to prioritize data visibility. 
- **Reflow:** On smaller screens, multi-column dashboard widgets reflow into a single-column stack with 8px gaps.

## Elevation & Depth

This design system rejects shadows, blurs, and gradients in favor of **Tonal Layering** and **Restrained Outlines**.

- **Level 0 (Base):** OLED Black (#000000). The foundation for the entire application.
- **Level 1 (Surfaces):** Graphite (#121212). Used for cards, list items, and secondary navigation containers.
- **Level 2 (Raised):** Graphite (#1E1E1E). Used for active input fields, modal overlays, and prominent headers.
- **Structural Depth:** Depth is communicated through 1px solid borders (#333333). When an element is active or selected, the border color transitions to Primary Cyan or the relevant status color (e.g., Red for critical alerts).

## Shapes

The shape language is industrial and "Soft," avoiding the playfulness of fully rounded or pill-shaped elements.

- **Standard Radius:** 4px for cards, buttons, and input fields. This provides just enough softening to prevent the UI from feeling aggressive while maintaining a rigid, technical structure.
- **Consistency:** All containers, whether they are small status chips or large data tables, must adhere to the 4px radius. 
- **Interactive States:** Buttons remain rectangular with 4px corners; do not use pill shapes for system actions.

## Components

- **Action Buttons:** Flat surfaces with 1px borders. Primary buttons use Cyan borders; destructive actions (STOP, FAILED) use Red. No gradients or inner shadows.
- **Status Chips:** Rectangular tags with `label-caps` typography. They must use clear status language: ONLINE, OFFLINE, STARTING, STOPPING, READY, RUNNING, QUEUED, WARNING, CRITICAL, FAILED, INTERRUPTED.
- **Horizontal Meters:** Used for CPU, RAM, and Storage. Background tracks use #333333 with filled indicators in Green, Amber, or Red.
- **Input Fields:** Base background of #1E1E1E with a 1px #333333 border. On focus, the border glows with Primary Cyan.
- **Technical Lists:** High-density rows with 1px bottom separators. Labels use Inter; values use JetBrains Mono.
- **Cards:** 1px Graphite borders, no background shadows. Content should be edge-to-edge where possible to maximize the data area.
- **Navigation:** Mobile uses a fixed bottom bar (44px height); Desktop uses a slim top bar with integrated global health metrics (Uptime/Load).