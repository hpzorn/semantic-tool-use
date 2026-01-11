# Visual Artifacts Ontology (VAO)

An ontology for modeling visual artifacts in presentations and social media content, enabling LLMs to generate and compose visuals through formal semantic specifications.

## Motivation

Current LLM-based visual generation relies on implicit knowledge from training data. By providing explicit semantic specifications of visual artifacts, we can:

1. **Generate novel visuals** - Specify visual compositions the LLM wasn't explicitly trained on
2. **Ensure consistency** - Define reusable visual patterns with formal constraints
3. **Enable composition** - Help LLMs stitch together complex visuals from atomic components
4. **Support validation** - Verify generated visuals conform to specifications

## Ontology Structure

```
visual-artifacts-core.ttl     # Core visual concepts (reuses existing ontologies)
├── imports/
│   ├── doco-subset.ttl       # Document Components (DoCO)
│   ├── schema-subset.ttl     # Schema.org visual types
│   └── dc-subset.ttl         # Dublin Core metadata
├── presentation-domain.ttl   # Presentation/slide-specific extensions
├── social-media-domain.ttl   # Social media format extensions
└── diagram-domain.ttl        # Diagram/visualization extensions
```

## Reused Ontologies

| Ontology | URI | Concepts Used |
|----------|-----|---------------|
| DoCO | `http://purl.org/spar/doco` | Figure, Section, Block, Caption |
| Schema.org | `https://schema.org/` | ImageObject, CreativeWork, MediaObject |
| Dublin Core | `http://purl.org/dc/terms/` | creator, title, description, format |
| Typoo | Custom subset | Font, Typeface, Typography properties |
| Open Graph | `http://ogp.me/ns#` | og:image, og:title (mapped) |

## Core Concepts

### Visual Element Hierarchy

```
vao:VisualArtifact (abstract)
├── vao:Presentation
│   └── vao:Slide
│       ├── vao:TitleSlide
│       ├── vao:ContentSlide
│       ├── vao:SectionSlide
│       └── ...
├── vao:SocialContent
│   ├── vao:Carousel
│   ├── vao:Card
│   └── vao:Post
├── vao:Diagram
│   ├── vao:Flowchart
│   ├── vao:SequenceDiagram
│   └── vao:ArchitectureDiagram
└── vao:VisualComponent
    ├── vao:TextBlock
    ├── vao:ImageBlock
    ├── vao:IconBlock
    └── vao:ChartBlock
```

### Layout System

```
vao:Layout
├── vao:GridLayout
│   ├── vao:columns (xsd:integer)
│   ├── vao:rows (xsd:integer)
│   └── vao:gutter (vao:Dimension)
├── vao:FlowLayout
│   └── vao:direction (horizontal|vertical)
└── vao:AbsoluteLayout
    └── vao:hasPosition → vao:Position
```

### Typography System

```
vao:Typography
├── vao:fontFamily (xsd:string)
├── vao:fontSize (vao:Dimension)
├── vao:fontWeight (100-900)
├── vao:fontStyle (normal|italic)
└── vao:textAlign (left|center|right|justify)

vao:TextStyle
├── vao:TitleStyle
├── vao:HeadingStyle
├── vao:BodyStyle
└── vao:CaptionStyle
```

### Color System

```
vao:Color
├── vao:hexValue (xsd:string, pattern: #[0-9A-Fa-f]{6})
├── vao:rgbValue (vao:RGBColor)
└── vao:semanticRole (primary|secondary|accent|background|text)

vao:ColorPalette
├── vao:primaryColor → vao:Color
├── vao:secondaryColor → vao:Color
├── vao:accentColors → vao:Color (multiple)
└── vao:backgroundColors → vao:Color (multiple)

vao:Gradient
├── vao:startColor → vao:Color
├── vao:endColor → vao:Color
├── vao:angle (xsd:integer, degrees)
└── vao:type (linear|radial)
```

### Spatial Properties

```
vao:Dimension
├── vao:value (xsd:decimal)
└── vao:unit (px|pt|mm|em|%)

vao:Position
├── vao:x (vao:Dimension)
├── vao:y (vao:Dimension)
└── vao:anchor (top-left|top-right|center|bottom-left|bottom-right)

vao:Spacing
├── vao:margin (vao:Dimension[4])
├── vao:padding (vao:Dimension[4])
└── vao:gap (vao:Dimension)
```

## Presentation Domain Extensions

### Slide Types (from typst-presentation skill)

| Slide Type | Description | Required Components |
|------------|-------------|---------------------|
| `vao:TitleSlide` | Opening slide with title/subtitle | title, subtitle, optional: author |
| `vao:SectionSlide` | Section divider | sectionTitle |
| `vao:ContentSlide` | Standard content | title, contentArea |
| `vao:TwoColumnSlide` | Side-by-side | title, leftColumn, rightColumn |
| `vao:ThreeColumnSlide` | Triple column | title, columns[3] |
| `vao:QuoteSlide` | Quote display | quoteText, attribution |
| `vao:CodeSlide` | Code display | codeBlock, optional: explanation |
| `vao:ImageSlide` | Full image | image, caption |
| `vao:CTASlide` | Call-to-action | question, ctaText, url |

### Slide Templates

```turtle
vao:ContentSlideTemplate a vao:SlideTemplate ;
    vao:hasLayout [
        a vao:GridLayout ;
        vao:columns 1 ;
        vao:rows 2
    ] ;
    vao:hasComponent [
        a vao:TitleArea ;
        vao:gridRow 1 ;
        vao:hasTypography vao:TitleStyle
    ] ;
    vao:hasComponent [
        a vao:ContentArea ;
        vao:gridRow 2 ;
        vao:hasTypography vao:BodyStyle
    ] ;
    vao:hasDecoration [
        a vao:AccentLine ;
        vao:position "below-title" ;
        vao:color vao:primaryColor
    ] .
```

## Social Media Domain Extensions

### Platform Formats

| Platform | Format | Dimensions | Constraints |
|----------|--------|------------|-------------|
| LinkedIn Carousel | PDF, 1:1 | 1080x1080px | 6-10 slides |
| Instagram Carousel | PDF, 1:1 or 4:5 | 1080x1080 or 1080x1350 | 2-10 slides |
| X/Twitter | Text thread | N/A | 280 chars/tweet |
| Mastodon | Text post | N/A | 500 chars |
| Substack | Markdown article | N/A | 1500-2500 words |

### Carousel Slide Types

```
vao:CarouselSlide
├── vao:HookSlide       # Attention-grabbing opener
├── vao:TipSlide        # Numbered tip with evidence
├── vao:StatSlide       # Statistics display
├── vao:QuoteSlide      # Quote with attribution
├── vao:StatementSlide  # Bold assertion
└── vao:CTASlide        # Call-to-action closer
```

### Content Brief Schema

```turtle
vao:ContentBrief a owl:Class ;
    rdfs:subClassOf vao:VisualArtifact ;
    vao:hasProperty vao:thesis ;
    vao:hasProperty vao:contrarianAngle ;
    vao:hasProperty vao:keyPoints ;
    vao:hasProperty vao:hook ;
    vao:hasProperty vao:question ;
    vao:hasProperty vao:callToAction ;
    vao:hasProperty vao:authorCredential .
```

## Diagram Domain Extensions

### Diagram Types

```
vao:Diagram
├── vao:Flowchart
│   └── vao:flowDirection (LR|RL|TB|BT)
├── vao:SequenceDiagram
│   └── vao:participants → vao:Actor[]
├── vao:StateDiagram
│   └── vao:states → vao:State[]
├── vao:ArchitectureDiagram
│   └── vao:components → vao:SystemComponent[]
├── vao:DataVisualization
│   ├── vao:BarChart
│   ├── vao:LineChart
│   └── vao:ScatterPlot
└── vao:IconScene
    └── vao:icons → vao:Icon[]
```

### Diagram Tools Mapping

| Diagram Type | Tool | Output Format |
|--------------|------|---------------|
| Flowchart | Mermaid | SVG |
| Sequence | Mermaid | SVG |
| DAG/Network | Graphviz | SVG |
| Architecture | D2 | SVG |
| Charts | Vega-Lite | SVG/PNG |
| Icon Scene | compose-scene.py | SVG |
| Maps | compose-map.py | SVG |
| Statistics | isotype.py | SVG |

## How This Helps LLMs

### 1. Novel Visual Generation

Instead of relying on training examples, the LLM can:
- Read the ontology to understand what visual components exist
- Combine components according to constraints
- Generate visuals it wasn't explicitly trained on

```sparql
# Query: What components can appear on a ContentSlide?
SELECT ?component ?constraint WHERE {
    vao:ContentSlide vao:allowsComponent ?component .
    ?component vao:hasConstraint ?constraint .
}
```

### 2. Composition Guidance

The ontology specifies how elements combine:

```turtle
vao:TwoColumnSlide vao:compositionRule [
    a vao:BalanceRule ;
    vao:leftWeight 0.5 ;
    vao:rightWeight 0.5 ;
    vao:alignItems "top"
] .
```

### 3. Validation

SHACL shapes can validate generated visuals:

```turtle
vao:CarouselShape a sh:NodeShape ;
    sh:targetClass vao:Carousel ;
    sh:property [
        sh:path vao:hasSlide ;
        sh:minCount 6 ;
        sh:maxCount 10 ;
        sh:message "LinkedIn carousel must have 6-10 slides"
    ] .
```

### 4. Style Transfer

Define style patterns that can be applied:

```turtle
vao:CorporateStyle a vao:VisualStyle ;
    vao:colorPalette vao:InovexPalette ;
    vao:typography vao:AtkinsonHyperlegible ;
    vao:hasGradient vao:DarkGradient ;
    vao:logoPlacement "bottom-right" .
```

## Example Usage

### Generating a Presentation Slide

```turtle
# Input specification
ex:mySlide a vao:ContentSlide ;
    vao:title "Key Findings" ;
    vao:hasLayout vao:TwoColumnLayout ;
    vao:leftColumn [
        a vao:BulletList ;
        vao:items ("Finding 1" "Finding 2" "Finding 3")
    ] ;
    vao:rightColumn [
        a vao:Diagram ;
        vao:diagramType vao:BarChart ;
        vao:data ex:findingsData
    ] ;
    vao:appliesStyle vao:CorporateStyle .
```

### Generating a Social Media Carousel

```turtle
ex:myCarousel a vao:LinkedInCarousel ;
    vao:fromBrief ex:contentBrief ;
    vao:slideCount 8 ;
    vao:hasSlide [
        a vao:HookSlide ;
        vao:position 1 ;
        vao:text "Stop doing X. Here's why."
    ] ;
    vao:hasSlide [
        a vao:TipSlide ;
        vao:position 2 ;
        vao:tipNumber 1 ;
        vao:title "First insight" ;
        vao:evidence "Supporting data"
    ] ;
    # ... more slides
    vao:appliesStyle vao:CorporateStyle .
```

## Files

- `visual-artifacts-core.ttl` - Core ontology with reused imports
- `presentation-domain.ttl` - Presentation/slide extensions
- `social-media-domain.ttl` - Social media format extensions
- `diagram-domain.ttl` - Diagram and visualization extensions
- `shapes/` - SHACL validation shapes
- `examples/` - Example instances

## References

- [DoCO - Document Components Ontology](https://sparontologies.github.io/doco/current/doco.html)
- [Schema.org](https://schema.org/)
- [Dublin Core](https://www.dublincore.org/)
- [Typoo Typography Ontology](https://github.com/FrederikeNeuber/typoo)
- [Open Graph Protocol](https://ogp.me/)
