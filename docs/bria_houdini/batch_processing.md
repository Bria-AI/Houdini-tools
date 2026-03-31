# Bria Batch Processing (TOP Node)

Process multiple images through Bria APIs using Houdini's PDG (Procedural Dependency Graph).

## Overview

Bria Batch is a TOP node that supports all Bria API operations as batch jobs. Each work item processes one image through the selected API. Combine with Wedge TOPs to sweep parameters like seed, prompt, or guidance scale.

## Modes

| Mode | API | Description |
|------|-----|-------------|
| `generate` | FIBO Generate | Text-to-image generation |
| `edit` | FIBO Edit | Prompt-based image editing |
| `enhancer` | Enhancer | Enhance image quality |
| `upscale` | Upscale | Increase resolution |
| `rmbg` | RMBG | Remove background |

## Edit Mode: Custom vs Preset

When mode is `edit`, a `prompt_mode` toggle selects between:

- **Custom** -- write your own prompt text
- **Preset** -- pick from 78 categorized recipe presets

### Preset Categories (9)

| Category | Presets | Examples |
|----------|---------|----------|
| Style | 18 | Hand-drawn, Anime, Film Noir, Cyberpunk, Watercolor |
| Weather | 8 | Sunny, Rainy, Thunderstorm, Snowy, Foggy |
| Seasons | 4 | Spring, Summer, Autumn, Winter |
| Time of Day | 8 | Dawn, Golden Hour, Midday, Night, Starry Night |
| Camera | 8 | Shallow DOF, Tilt Shift, Wide Angle, Macro, Fisheye |
| Lighting | 8 | Dramatic Side, Rim Backlight, Neon Glow, Volumetric Rays |
| Clean / Artifacts | 8 | Color Correction, Fix Artifacts, Remove Noise, Sharpen |
| AI Corrections | 8 | Fix Face, Fix Eyes, Fix Hands, Fix Hair, Fix Background |
| Object Edits | 8 | Add Vegetation, Add People, Add Clouds, Age/Weathering, Modernize |

Note: Custom (no presets) and Compositing (requires per-image input) categories are excluded from batch. Four targeted object presets (delete, replace, change color, change material) are also excluded since they require object-specific input.

Selecting a preset auto-fills the `prompt` parameter. You can edit the prompt text after selection.

## PDG Attributes

Work item attributes override node parameter defaults. Use a Wedge TOP upstream to sweep these values across work items.

### Common Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `mode` | string | Batch mode (generate/edit/enhancer/upscale/rmbg) |
| `input_image` | string | Input image file path (from upstream work item) |
| `prompt` | string | Text prompt (generate/edit modes) |
| `negative_prompt` | string | Negative prompt |
| `seed` | int | Random seed |
| `guidance_scale` | float | Guidance scale (generate/edit) |
| `steps_num` | int | Inference steps (generate/edit) |
| `structured_prompt` | string | VGL JSON structured prompt |
| `auto_struct` | int | Auto-generate structured prompt (0/1) |

### Mode-Specific Attributes

| Attribute | Modes | Description |
|-----------|-------|-------------|
| `aspect_ratio` | generate | Output aspect ratio |
| `pipeline` | generate | Generation pipeline |
| `resolution` | enhancer | Target resolution (1MP/2MP/4MP) |
| `desired_resolution` | upscale | Upscale factor (2x/4x) |
| `preserve_alpha` | enhancer, upscale, rmbg | Preserve alpha channel |
| `keep_original_size` | rmbg | Keep original dimensions |
| `force_bg_detection` | rmbg | Force background detection |
| `content_moderation_input` | enhancer, upscale, rmbg | Input content moderation |
| `content_moderation_output` | enhancer, upscale, rmbg | Output content moderation |

## Example PDG Network

```
File Pattern TOP          (scan input images)
        |
   Wedge TOP              (sweep seed: 1-10)
        |
  Bria Batch TOP          (mode: edit, prompt: "golden hour lighting")
        |
   Wait for All TOP
        |
    (review results)
```

1. **File Pattern** scans a directory for input images
2. **Wedge** creates 10 work items per image with different seeds
3. **Bria Batch** processes each work item through FIBO Edit
4. Results are saved to the output directory with metadata sidecars

## MPlay Preview

Results can be previewed in MPlay. The node uses `imdisplay` (if available) or falls back to `mplay` or `os.startfile()` on Windows.

## Output

Each work item produces:
- Result image (PNG/JPEG depending on API response)
- Metadata sidecar (JSON) with API response, timing, and request parameters
- `result_path` attribute on the work item pointing to the output file
