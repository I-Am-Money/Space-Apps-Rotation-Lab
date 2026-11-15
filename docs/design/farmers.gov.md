# Design Map

Source: https://www.farmers.gov (home page, 1440x900, captured 2026-11-15)

## Spacing Scale
- 5px, 10px, 20px, 30px, 45px inside components
- About 60 to 100px of plain ground between sections; 80px centred rules mark two breaks
- Content column about 1060px, centred

## Font Hierarchy
- Hero h1: 38px / 700 / Public Sans
- h2: 28px / 700 · h3: 23px / 700 · h4: 20px / 700
- Body: 18px / 400, line-height 28px
- Small: 16px, 14px, 12px
- One family (Public Sans) on 443 of 446 text elements

## Color Palette
- `#F7F7F7` page ground (52% of painted area)
- `#FFFFFF` card and header surfaces (40%)
- `#212121` text
- `#006546` navigation bar, hero overlay, every link
- `#E31C3D` alert text only
- `#E0E0E0` row rules
- Grays are pure, with no hue tint

## Image Ratios
- Hero photograph 2.67:1, full width, green overlay on the left 55%
- Thumbnails 1.97:1; tool icons are 64px line drawings

## Component Tokens
- Radius: 2px on cards and inputs, 0px on buttons
- Card shadow: `0 3px 14px 0 #D8D8D8`, one layer
- Header shadow: `0 1px 4px 0 #BBBBBB`
- Grid: 2 columns for lists, 3 columns for tool cards, 20px gutter
- Call to action: underlined 700-weight green link with a circled arrow
- Motion: `0.2s ease-in-out` on links and menus only; reduced-motion rule present

---

# Taste DNA

### Green means you can press it
- **Trigger**: When the designers had a brand green and a page full of links, alerts and dates
- **Decision**: They spent the green only on navigation and links, over spreading it across headings, icons and backgrounds as decoration
- **Reason**: A reader who is unsure of a website needs one dependable rule. If green always means "this goes somewhere", they stop testing things with the cursor.
- **Evidence**: `#006546` on 44 interactive elements and 37 link texts; headings stay `#212121`; neutrals cover 92% of the painted area; red `#E31C3D` is kept for one service alert

### Say the action in a sentence
- **Trigger**: When the designers needed calls to action on eleven cards
- **Decision**: They chose underlined text links that name the result ("Apply for a Farm Loan") over filled buttons with short labels, and left out button fills, icon-only controls and hover effects
- **Reason**: A person filling in a government form on a slow connection trusts words more than shapes. A sentence cannot be misread the way a "Submit" button or an icon can.
- **Evidence**: 12+ underlined 700-weight links with a circled arrow; button radius 0px; only two filled buttons on the page, both in forms

### Make the reading size the big size
- **Trigger**: When the designers set the type scale
- **Decision**: They chose an 18px body with a modest 38px headline over a small body under a very large display headline
- **Reason**: The audience reads the paragraph, not the slogan, often outdoors or past fifty, so the size goes into ordinary sentences.
- **Evidence**: 18px is the most frequent size (37 uses) with 28px line-height; h1 at 38px is 2.1x body; 4 heading sizes, all weight 700

### One container, learned once
- **Trigger**: When the designers had news, dates, tools, topics and blog posts to hold
- **Decision**: They chose one white card with a 2px corner and a single gray shadow for all of them, over a different treatment per content type
- **Reason**: Every new kind of box is something to work out. With one box, attention goes to what is inside it.
- **Evidence**: `0 3px 14px #D8D8D8` on 10 cards; 2px radius on 15 elements; no card inside a card; the only variation is an 80x6px colored bar on two cards
