# Markdown to PDF Converter — Formatting & Feature Specification

This specification defines the formatting rules, extended syntax, and utility classes supported by the Markdown-to-PDF converter engine. Any LLM or autonomous agent producing Markdown documents for PDF compilation should follow these guidelines.

---

## 1. Document Structure & Typography

- **Headings**: Use standard ATX headings (`#`, `##`, `###`, `####`). Headings automatically enforce `page-break-after: avoid` to prevent orphan titles at page bottoms.
- **Paragraphs**: Standard text paragraphs are rendered with justified alignment (`text-align: justify`) and proportional line height.
- **Lists**: Ordered and unordered lists (`-`, `*`, `1.`) are indented with compact spacing.
- **Blockquotes**: Markdown `>` blockquotes are formatted in italic with an indented margin.

---

## 2. Image Placement, Sizing & Alignment

The converter provides extended Markdown image syntax as well as direct HTML support.

### Extended Markdown Syntax
```markdown
![Caption Text|class1|class2](path/to/image.png)
```
The text preceding the first pipe (`|`) becomes the figure caption (`<figcaption>`). The tokens following the pipes are applied as CSS classes to both the `<figure>` container and the `<img>` element.

#### Examples:
- Centered image at 50% page width with caption:
  ```markdown
  ![Circuit Diagram|center|w-50](diagram.png)
  ```
- Centered screenshot with subtle academic border:
  ```markdown
  ![Execution Evidence|center|screenshot](terminal.png)
  ```
- Floating image on the right at 25% width:
  ```markdown
  ![Icon|right|w-25](icon.png)
  ```
- Image with no caption:
  ```markdown
  ![|center|w-75](chart.png)
  ```

### Utility Classes Reference

| Category | Class | Description |
|---|---|---|
| **Alignment** | `center`, `img-center` | Centers element in block mode (`margin-left: auto; margin-right: auto`) |
| **Alignment** | `left` | Floats element to the left with right margin |
| **Alignment** | `right` | Floats element to the right with left margin |
| **Width** | `w-25` | Sets element width to 25% of printable area |
| **Width** | `w-50` | Sets element width to 50% of printable area |
| **Width** | `w-75` | Sets element width to 75% of printable area |
| **Width** | `w-100` | Sets element width to 100% of printable area |
| **Max Height** | `small` | Caps height at 2.2 inches (compact diagrams, signatures) |
| **Max Height** | `medium` | Caps height at 4.0 inches (standard charts and schematics) |
| **Max Height** | `large` | Caps height at 6.5 inches (full-page vertical diagrams) |
| **Style** | `screenshot` | Adds subtle border (`#cccccc`), margin, and centers image |

---

## 3. Advanced HTML Elements

### Explicit Figures with Captions
```html
<figure class="center w-50">
  <img src="schematic.png" class="center w-50" alt="Circuit Schematic" />
  <figcaption>Figure 1: Operational amplifier closed-loop schematic</figcaption>
</figure>
```

### Side-by-Side Image Grids (`image-grid-2`)
To display two images or figures side-by-side (e.g. theoretical vs. experimental comparison):
```html
<div class="image-grid-2">
  <figure>
    <img src="simulation.png" alt="Simulation" />
    <figcaption>Simulation Response</figcaption>
  </figure>
  <figure>
    <img src="measurement.png" alt="Oscilloscope Measurement" />
    <figcaption>Physical Measurement</figcaption>
  </figure>
</div>
```

---

## 4. Path Resolution & Windows WSL Normalization

The converter automatically resolves local image paths and embeds them as Base64 Data URIs:
1. Relative path from the Markdown file's directory.
2. Absolute filesystem paths (Linux / Unix).
3. **Automatic Windows to WSL Path Normalization**:
   Windows paths (e.g., `C:\Users\username\Pictures\photo.png` or `C:/...`) pasted into Markdown in a WSL environment are automatically translated to `/mnt/c/Users/username/Pictures/photo.png`.
   Accidental quotes surrounding file paths are stripped automatically.

---

## 5. Page Break Control

For clean pagination across multi-page documents:
- Force break after an element:
  ```html
  <div class="page-break"></div>
  ```
- Force break before an element via CSS class:
  ```html
  <h2 class="page-break-before">Section Title</h2>
  ```
- Force break after an element via CSS class:
  ```html
  <div class="page-break-after">Content</div>
  ```

---

## 6. Code Blocks & Data Tables

### Code Blocks
Fenced code blocks with language identifiers render with syntax formatting, subtle background, and `page-break-inside: avoid`:
````markdown
```python
def calculate_gain(r_f: float, r_in: float) -> float:
    return 1.0 + (r_f / r_in)
```
````

### Tables
Standard GitHub Flavored Markdown tables are rendered with clear borders, bold headers, and page break prevention:
```markdown
| Parameter | Theoretical | Measured | Error (%) |
|---|---|---|---|
| Voltage Out | 5.00 V | 4.95 V | 1.0% |
| Current In  | 2.50 mA | 2.52 mA | 0.8% |
```

---

## 7. Converter CLI Invocation

- **Convert a single file**:
  ```bash
  python3 -m bookish_pkg.converter path/to/document.md [output/destination.pdf]
  ```

- **Convert a directory of Markdown files**:
  ```bash
  python3 -m bookish_pkg.converter path/to/directory/ [output/directory/]
  ```
