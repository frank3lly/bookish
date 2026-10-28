# Rules & Formatting Specification for Bookish PDF Converter

This document defines the exact formatting and structural rules for Markdown (`.md`) files to be converted into clean, professional academic PDFs using `bookish_pkg.converter`. Pass this guide to AI models (ChatGPT, Claude, Gemini) when requesting homework drafts or reports.

---

## 1. Academic Cover Page (Presentation Sheet)

Every document must start with the cover page HTML block at the very top. Do **not** place any Markdown text before this block.

```html
<div class="cover-page">
  <img src="logo.jpeg" alt="Universidad Central del Este" class="cover-logo" />
  <h2>Facultad de Ciencias e Ingenierías</h2>
  <h3>Escuela de Ingeniería de Software</h3>

  <p><strong>Asignatura:</strong> [CÓDIGO DE ASIGNATURA]</p>
  <p><strong>Asignación:</strong> [TÍTULO DE LA TAREA]</p>
  <p><strong>Estudiante:</strong> [NOMBRE DEL ESTUDIANTE]</p>
  <p><strong>Matrícula:</strong> [MATRÍCULA]</p>
  <p><strong>Fecha Límite:</strong> [FECHA DE ENTREGA]</p>
</div>
```

- **Note on Logo**: `<img src="logo.jpeg" ... />` is automatically replaced with the encoded institutional logo during PDF compilation.
- **Page Break**: The `.cover-page` container automatically forces a clean page break after it.

---

## 2. Body Text & Typography Rules

1. **Academic Tone & Paragraph Flow**:
   - Write in a natural, mature university student voice.
   - Use fluid paragraphs (2–4 paragraphs per section).
   - Avoid generic AI summary phrases like *"En resumen"*, *"Es importante destacar"*, *"Sin lugar a dudas"*, or *"En conclusión"*.

2. **Heading Hierarchy**:
   - Primary section headings: `### Heading Title` or `## Heading Title`.
   - Subsection titles: `#### Subsection Title`.

3. **No Excessive Lists**:
   - Explain concepts using cohesive narrative paragraphs instead of bullet points, unless explicitly requested by the assignment instructions.

---

## 3. Images, Screenshots & Evidence

Images can be inserted using standard Markdown or HTML `<img>` tags.

### Supported Syntax:
- **HTML Tag** (Recommended for screenshots):
  ```html
  <img src="captura_registro_empleados.png" alt="Descripción de la captura" class="screenshot" />
  ```
- **Markdown Image Syntax**:
  ```markdown
  ![Descripción de la imagen](captura_registro_empleados.png)
  ```

### Image Path Resolution:
The converter automatically resolves and embeds images into Base64 Data URIs from:
1. Relative path to the `.md` file's location.
2. Direct or absolute system path.
3. Fallback repository directory: `data/images/<filename>`.

Adding `class="screenshot"` applies a clean border and centers the screenshot within page margins.

---

## 4. Code Blocks & Formatting

All code snippets must use fenced code blocks with language identifiers:

````markdown
```csharp
public class Empleado : Cliente
{
    private string cargo;
    private decimal salario;

    public Empleado(string codigo, string nombre, string cargo, decimal salario)
        : base(codigo, nombre)
    {
        this.cargo = cargo;
        this.salario = salario;
    }
}
```
````

- Inline code should use single backticks: `` `private` ``, `` `protected` ``.

---

## 5. Data Tables & Specifications

Data tables must use standard Markdown table syntax:

```markdown
| Modificador | Campo | Propósito |
|---|---|---|
| `protected` | `codigo`, `nombre` | Heredados por la clase derivada `Empleado`. |
| `private` | `salario` | Dato sensible restringido a la propia clase. |
```

---

## 6. Execution & Usage Commands

### Batch conversion (default directory `data/drafts/` -> configured output directory):
```bash
python3 -m bookish_pkg.converter
```

### Convert a specific directory of Markdown files:
```bash
python3 -m bookish_pkg.converter /ruta/a/la/carpeta/ [ruta/de/salida/]
```

### Convert a single Markdown file:
```bash
python3 -m bookish_pkg.converter /ruta/a/mi_tarea.md [/ruta/de/salida/mi_tarea.pdf]
```
