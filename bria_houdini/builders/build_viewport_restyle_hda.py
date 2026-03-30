"""
Bria Viewport Restyle HDA Builder Script for Houdini 21+ / Copernicus

Run in Houdini Python Shell:
    exec(open("<repo>/bria_houdini/builders/build_viewport_restyle_hda.py").read())

Adapted from MagAIRender HDA builder for use with Bria API.
"""

import hou
import os
from pathlib import Path

# Resolve repo root relative to this script's location.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else None
if _THIS_DIR:
    _REPO_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", ".."))
else:
    _REPO_ROOT = os.environ.get("BRIA_HOUDINI_REPO", os.getcwd())

# Configuration
HDA_NAME = "bria_viewport_restyle"
HDA_LABEL = "Bria Viewport Restyle"
HDA_VERSION = "1.5"
HDA_FILE = os.path.join(_REPO_ROOT, "hda", "bria_viewport_restyle.hda")
CORE_MODULE_PATH = os.path.join(_REPO_ROOT, "bria_houdini", "houdini", "nodes", "viewport_restyle.py")

os.makedirs(os.path.dirname(HDA_FILE), exist_ok=True)


# ============================================================
# Shared API Key callback scripts (identical across all tools)
# ============================================================

def get_save_key_callback():
    return '''
from bria_copernicus.ui.hda_api_key import save_api_key_action
save_api_key_action(kwargs["node"])
'''

def get_enter_new_key_callback():
    return '''
from bria_copernicus.ui.hda_api_key import enter_new_key_action
enter_new_key_action(kwargs["node"])
'''

def get_cancel_new_key_callback():
    return '''
from bria_copernicus.ui.hda_api_key import cancel_new_key_action
cancel_new_key_action(kwargs["node"])
'''

def build_api_key_tab():
    """Build the API Key tab parameters (shared across all HDAs)."""
    api_folder = hou.FolderParmTemplate("api_key_tab", "API Key", folder_type=hou.folderType.Tabs)

    api_status = hou.StringParmTemplate("api_key_status", "Status", 1, default_value=["No API key configured"])
    api_status.setHelp("Current API key status")
    api_status.setConditional(hou.parmCondType.DisableWhen, "{ api_key_status != __never_match__ }")
    api_folder.addParmTemplate(api_status)

    api_folder.addParmTemplate(hou.SeparatorParmTemplate("api_sep1"))

    api_input = hou.StringParmTemplate("api_key_input", "API Key", 1, default_value=[""])
    api_input.setHelp("Enter your Bria API key")
    api_input.setTags({"editor": "0"})
    api_input.setConditional(hou.parmCondType.HideWhen, "{ api_key_configured == 1 api_key_entry_mode == 0 }")
    api_folder.addParmTemplate(api_input)

    save_btn = hou.ButtonParmTemplate("save_key_btn", "Save Key",
        script_callback=get_save_key_callback(), script_callback_language=hou.scriptLanguage.Python)
    save_btn.setConditional(hou.parmCondType.HideWhen, "{ api_key_configured == 1 api_key_entry_mode == 0 }")
    api_folder.addParmTemplate(save_btn)

    cancel_btn = hou.ButtonParmTemplate("cancel_new_key_btn", "Cancel",
        script_callback=get_cancel_new_key_callback(), script_callback_language=hou.scriptLanguage.Python)
    cancel_btn.setConditional(hou.parmCondType.HideWhen, "{ api_key_entry_mode == 0 }")
    api_folder.addParmTemplate(cancel_btn)

    new_key_btn = hou.ButtonParmTemplate("enter_new_key_btn", "Enter New Key",
        script_callback=get_enter_new_key_callback(), script_callback_language=hou.scriptLanguage.Python)
    new_key_btn.setConditional(hou.parmCondType.HideWhen, "{ api_key_configured == 0 } { api_key_entry_mode == 1 }")
    api_folder.addParmTemplate(new_key_btn)

    configured_toggle = hou.ToggleParmTemplate("api_key_configured", "API Key Configured", default_value=False)
    configured_toggle.hide(True)
    api_folder.addParmTemplate(configured_toggle)

    entry_mode_toggle = hou.ToggleParmTemplate("api_key_entry_mode", "Entry Mode", default_value=False)
    entry_mode_toggle.hide(True)
    api_folder.addParmTemplate(entry_mode_toggle)

    return api_folder


def build_hda():
    """Build the Bria Viewport Restyle HDA."""

    print("=" * 60)
    print("Building Bria Viewport Restyle HDA")
    print("=" * 60)

    # Remove existing HDA if present
    if os.path.exists(HDA_FILE):
        print(f"\nRemoving existing HDA...")
        try:
            for defn in hou.hda.definitionsInFile(HDA_FILE):
                defn.destroy()
        except:
            pass
        try:
            os.remove(HDA_FILE)
        except:
            pass

    # Create a temporary node in /obj
    print("\nStep 1: Creating temporary network...")
    obj = hou.node("/obj")
    temp_node = obj.createNode("geo", "temp_bria_restyle_builder")

    # Create the digital asset
    print("\nStep 2: Creating HDA...")
    hda_node = temp_node.createDigitalAsset(
        name=HDA_NAME,
        hda_file_name=HDA_FILE,
        description=HDA_LABEL,
        min_num_inputs=0,
        max_num_inputs=0,
        version=HDA_VERSION
    )

    print(f"  Created: {hda_node.type().name()}")

    # Get the HDA definition
    hda_definition = hda_node.type().definition()

    # Build parameters
    print("\nStep 3: Adding parameters...")
    ptg = hou.ParmTemplateGroup()

    # === API KEY TAB (first for discoverability) ===
    ptg.append(build_api_key_tab())

    # Create main folder
    main_folder = hou.FolderParmTemplate(
        "bria_restyle_folder",
        "Bria Viewport Restyle",
        folder_type=hou.folderType.Tabs
    )

    # 1. Enable toggle
    enable = hou.ToggleParmTemplate("enable", "Enable", default_value=True)
    main_folder.addParmTemplate(enable)

    # 2. Separator
    main_folder.addParmTemplate(hou.SeparatorParmTemplate("sep1"))

    # 3. Prompt - Multi-line text field
    prompt = hou.StringParmTemplate(
        "prompt",
        "Style Prompt",
        1,
        default_value=["A photorealistic rendering with detailed textures, professional lighting, and cinematic quality"],
        string_type=hou.stringParmType.Regular
    )
    prompt.setTags({"editor": "1", "editorlines": "8"})
    prompt.setHelp("Describe the desired style for the restyled viewport (e.g., 'watercolor painting', 'cyberpunk neon aesthetic')")
    main_folder.addParmTemplate(prompt)

    # 4. Separator
    main_folder.addParmTemplate(hou.SeparatorParmTemplate("sep2"))

    # 5. Create Render Camera button
    create_camera_btn = hou.ButtonParmTemplate(
        "create_camera",
        "Create Render Camera"
    )
    create_camera_btn.setScriptCallback("hou.phm().create_camera_callback()")
    create_camera_btn.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    create_camera_btn.setHelp("Create a camera at the current viewport position")
    main_folder.addParmTemplate(create_camera_btn)

    # 6. Resolution menu
    resolution_menu = hou.MenuParmTemplate(
        "resolution",
        "Resolution",
        menu_items=["1024x1024", "1536x1024", "1024x1536"],
        menu_labels=["1024x1024 (Square)", "1536x1024 (Landscape)", "1024x1536 (Portrait)"],
        default_value=0
    )
    resolution_menu.setHelp("Output resolution for viewport capture and result")
    main_folder.addParmTemplate(resolution_menu)

    # 7. Separator
    main_folder.addParmTemplate(hou.SeparatorParmTemplate("sep3"))

    # 8. Restyle Viewport button
    restyle_btn = hou.ButtonParmTemplate(
        "restyle_viewport",
        "Restyle Viewport"
    )
    restyle_btn.setScriptCallback("hou.phm().restyle_viewport_callback()")
    restyle_btn.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    restyle_btn.setTags({"button_icon": "COP2_colormap"})
    restyle_btn.setHelp("Capture viewport and restyle with Bria AI")
    main_folder.addParmTemplate(restyle_btn)

    # 10. Status display
    status = hou.StringParmTemplate(
        "status",
        "Status",
        1,
        default_value=["Ready"]
    )
    status.setHelp("Current processing status")
    main_folder.addParmTemplate(status)

    ptg.append(main_folder)

    # === SETTINGS TAB ===
    settings_folder = hou.FolderParmTemplate(
        "settings",
        "Settings",
        folder_type=hou.folderType.Tabs
    )

    # FIBO Edit toggle
    use_fibo_edit = hou.ToggleParmTemplate("use_fibo_edit", "Use FIBO Edit Engine", default_value=True)
    use_fibo_edit.setHelp("Use FIBO Edit engine (recommended). Disable to use legacy reimagine.\nFIBO Edit offers higher quality, guidance control, and negative prompts.")
    settings_folder.addParmTemplate(use_fibo_edit)

    # Separator
    settings_folder.addParmTemplate(hou.SeparatorParmTemplate("sep_engine"))

    # Guidance scale — FIBO Edit only (hidden when FIBO Edit is off)
    guidance_scale = hou.IntParmTemplate(
        "guidance_scale", "Guidance Scale", 1,
        default_value=[5],
        min=1, max=20,
        min_is_strict=True,
        max_is_strict=True
    )
    guidance_scale.setHelp("How strongly the edit follows the instruction (1-20).\nHigher = more dramatic style change.\nLower = subtler, more faithful to original.")
    guidance_scale.setConditional(hou.parmCondType.HideWhen, "{ use_fibo_edit == 0 }")
    settings_folder.addParmTemplate(guidance_scale)

    # Negative prompt — FIBO Edit only (hidden when FIBO Edit is off)
    negative_prompt = hou.StringParmTemplate(
        "negative_prompt", "Negative Prompt", 1,
        default_value=[""],
        string_type=hou.stringParmType.Regular
    )
    negative_prompt.setHelp("Elements to exclude from the restyled result (e.g., 'blur, noise, artifacts').\nFIBO Edit only.")
    negative_prompt.setTags({"editor": "1"})
    negative_prompt.setConditional(hou.parmCondType.HideWhen, "{ use_fibo_edit == 0 }")
    settings_folder.addParmTemplate(negative_prompt)

    # Structure influence slider — Legacy reimagine only (hidden when FIBO Edit is on)
    structure_influence = hou.FloatParmTemplate(
        "structure_influence",
        "Structure Influence",
        1,
        default_value=[0.75],
        min=0.0,
        max=1.0,
        min_is_strict=True,
        max_is_strict=True
    )
    structure_influence.setHelp("How much to preserve the viewport composition (0.0-1.0).\n- Higher = preserve more structure, subtle style changes\n- Lower = more creative freedom, dramatic style changes\n- 0.75 is a good balance\nLegacy reimagine only.")
    structure_influence.setConditional(hou.parmCondType.HideWhen, "{ use_fibo_edit == 1 }")
    settings_folder.addParmTemplate(structure_influence)

    # Separator
    settings_folder.addParmTemplate(hou.SeparatorParmTemplate("sep_settings"))

    # Seed
    seed_parm = hou.IntParmTemplate(
        "seed", "Seed", 1,
        default_value=[0],
        min=0, max=2147483647,
        min_is_strict=True
    )
    seed_parm.setHelp("Random seed for reproducible results (0 = random)")
    settings_folder.addParmTemplate(seed_parm)

    # Steps num — expanded range for FIBO Edit (1-100 vs legacy 12-50)
    steps_num = hou.IntParmTemplate(
        "steps_num", "Generation Steps", 1,
        default_value=[0],
        min=0, max=100,
        min_is_strict=True,
        max_is_strict=True
    )
    steps_num.setHelp("Number of generation steps (0 = use default).\nFIBO Edit: 1-100 (default 50).\nLegacy: 12-50.\nHigher = better quality but slower.")
    settings_folder.addParmTemplate(steps_num)

    # Separator
    settings_folder.addParmTemplate(hou.SeparatorParmTemplate("sep_settings2"))

    # Content moderation — legacy only (hidden when FIBO Edit is on)
    content_mod = hou.ToggleParmTemplate("content_moderation", "Content Moderation", default_value=True)
    content_mod.setHelp("Enable Bria content moderation (legacy reimagine only)")
    content_mod.setConditional(hou.parmCondType.HideWhen, "{ use_fibo_edit == 1 }")
    settings_folder.addParmTemplate(content_mod)

    # Use cache toggle
    use_cache = hou.ToggleParmTemplate("use_cache", "Use Cache", default_value=True)
    use_cache.setHelp("Cache results to avoid redundant API calls")
    settings_folder.addParmTemplate(use_cache)

    ptg.append(settings_folder)

    # === APPLY TEXTURE TAB ===
    apply_folder = hou.FolderParmTemplate(
        "apply_texture_folder",
        "Apply Texture",
        folder_type=hou.folderType.Tabs
    )

    # Source image dropdown (dynamically populated via item generator script)
    source_image = hou.StringParmTemplate(
        "source_image",
        "Source Image",
        1,
        default_value=[""],
        string_type=hou.stringParmType.Regular
    )
    source_image.setMenuType(hou.menuType.StringReplace)
    # Dynamic menu script to populate with available images
    menu_script = '''
import os
import glob
try:
    import hou
    output_dir = hou.expandString("$HIP/bria_textures")
except:
    output_dir = os.path.expanduser("~/bria_textures")

menu = []
if os.path.exists(output_dir):
    files = sorted(glob.glob(os.path.join(output_dir, "bria_restyle_*.png")),
                   key=os.path.getmtime, reverse=True)
    for f in files[:20]:
        name = os.path.basename(f)
        display = name.replace("bria_restyle_", "").replace(".png", "")
        menu.extend([f, display])

if not menu:
    menu = ["", "(No images found)"]
return menu
'''
    source_image.setItemGeneratorScript(menu_script)
    source_image.setItemGeneratorScriptLanguage(hou.scriptLanguage.Python)
    source_image.setHelp("Select a previously generated restyle image to apply as texture")
    apply_folder.addParmTemplate(source_image)

    # Refresh button
    refresh_btn = hou.ButtonParmTemplate(
        "refresh_images",
        "Refresh Image List"
    )
    refresh_btn.setScriptCallback("hou.phm().refresh_image_list_callback()")
    refresh_btn.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    refresh_btn.setHelp("Refresh the list of available images")
    apply_folder.addParmTemplate(refresh_btn)

    # Separator
    apply_folder.addParmTemplate(hou.SeparatorParmTemplate("sep_apply1"))

    # Apply Texture button
    apply_btn = hou.ButtonParmTemplate(
        "apply_texture",
        "Apply Texture"
    )
    apply_btn.setScriptCallback("hou.phm().apply_texture_callback()")
    apply_btn.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    apply_btn.setTags({"button_icon": "SHOP_material"})
    apply_btn.setHelp("Apply selected texture to all displayed geometry objects using camera projection")
    apply_folder.addParmTemplate(apply_btn)

    # Separator
    apply_folder.addParmTemplate(hou.SeparatorParmTemplate("sep_apply2"))

    # Expand section header
    expand_label = hou.LabelParmTemplate(
        "expand_label",
        "Image Expansion",
        column_labels=["Expand image for larger coverage:"]
    )
    apply_folder.addParmTemplate(expand_label)

    # Padding percentage
    padding_pct = hou.IntParmTemplate(
        "padding_percent",
        "Expansion Padding %",
        1,
        default_value=[25],
        min=5,
        max=100,
        min_is_strict=True,
        max_is_strict=True
    )
    padding_pct.setHelp("Percentage of image size to add as padding on each edge.\nHigher values give more room for camera movement.")
    apply_folder.addParmTemplate(padding_pct)

    # Expansion prompt
    expand_prompt = hou.StringParmTemplate(
        "expand_prompt",
        "Expansion Prompt",
        1,
        default_value=[""],
        string_type=hou.stringParmType.Regular
    )
    expand_prompt.setHelp("Guide what gets generated in expanded areas (optional).\nLeave empty for automatic continuation of the image.")
    expand_prompt.setTags({"editor": "1"})
    apply_folder.addParmTemplate(expand_prompt)

    # Expand and Apply button
    expand_apply_btn = hou.ButtonParmTemplate(
        "expand_and_apply",
        "Expand and Apply"
    )
    expand_apply_btn.setScriptCallback("hou.phm().expand_and_apply_callback()")
    expand_apply_btn.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    expand_apply_btn.setTags({"button_icon": "COP2_expand"})
    expand_apply_btn.setHelp("Expand image using Bria AI to add padding, then apply as texture")
    apply_folder.addParmTemplate(expand_apply_btn)

    # Separator
    apply_folder.addParmTemplate(hou.SeparatorParmTemplate("sep_apply3"))

    # PBR toggle
    pbr_toggle = hou.ToggleParmTemplate(
        "use_pbr",
        "Use PBR Material",
        default_value=False
    )
    pbr_toggle.setHelp("OFF = OpenGL-optimized shader (viewport only)\nON = Principled Shader (renderable with Karma/Mantra)")
    apply_folder.addParmTemplate(pbr_toggle)

    ptg.append(apply_folder)

    # === INFO TAB ===
    info_folder = hou.FolderParmTemplate(
        "info",
        "Info",
        folder_type=hou.folderType.Tabs
    )

    info_label = hou.LabelParmTemplate(
        "info_label",
        "Info",
        column_labels=["Bria Viewport Restyle v" + HDA_VERSION]
    )
    info_folder.addParmTemplate(info_label)

    info_text = hou.LabelParmTemplate(
        "info_text",
        "",
        column_labels=["Captures viewport and restyles with Bria AI"]
    )
    info_folder.addParmTemplate(info_text)

    info_text2 = hou.LabelParmTemplate(
        "info_text2",
        "",
        column_labels=["Use Seed in Settings for reproducible results"]
    )
    info_folder.addParmTemplate(info_text2)

    ptg.append(info_folder)

    # Apply parameters
    hda_definition.setParmTemplateGroup(ptg)
    print("  Parameters added")

    # Read and embed the core module
    print("\nStep 4: Embedding Python module...")
    with open(CORE_MODULE_PATH, 'r') as f:
        core_module_code = f.read()

    # Append API key refresh function to the core module
    api_key_refresh = '''

# --- API Key auto-load (appended by builder) ---
def refresh_key(kwargs):
    try:
        from bria_copernicus.ui.hda_api_key import refresh_api_key_state
        refresh_api_key_state(kwargs["node"])
    except Exception:
        pass
'''
    hda_definition.addSection("PythonModule", core_module_code + api_key_refresh)
    print("  Python module embedded (with API key refresh)")

    # Event scripts for auto-loading API key
    event_handler = "kwargs['node'].hdaModule().refresh_key(kwargs)"
    hda_definition.addSection("OnCreated", event_handler)
    hda_definition.addSection("OnLoaded", event_handler)
    try:
        hda_definition.setExtraFileOption("OnCreated/IsPython", True)
        hda_definition.setExtraFileOption("OnLoaded/IsPython", True)
    except AttributeError:
        pass

    # Set icon
    try:
        hda_definition.setIcon("OBJ_camera")
    except:
        pass

    # Set help
    help_text = """= Bria Viewport Restyle =

Captures the Houdini viewport and restyles it using Bria's AI.
Uses the FIBO Edit engine by default for high-quality structured edits.
Can also project the styled image back onto geometry as a texture.

== Basic Usage ==
1. Position your viewport with the desired camera angle
2. Click "Create Render Camera" to save the view
3. Enter a style prompt (e.g., "watercolor painting", "cyberpunk neon")
4. Adjust Guidance Scale in Settings (higher = more dramatic change)
5. Click "Restyle Viewport"
6. Result opens in MPlay and is saved to $HIP/bria_textures/

== Apply Texture ==
Project the styled image back onto your geometry:
1. Make sure displayed geometry objects exist in /obj
2. Go to "Apply Texture" tab
3. Select an image from the dropdown
4. Click "Apply Texture" to project onto geometry

== Expand and Apply ==
For more camera freedom, expand the image first:
1. Select an image and set Expansion Padding %
2. Click "Expand and Apply"
3. Bria AI extends the image beyond its boundaries
4. Camera is automatically adjusted to match

== Settings ==
* FIBO Edit Engine: On by default. Uses Bria's FIBO Edit model for
  higher quality results. Disable to fall back to legacy reimagine.
* Guidance Scale (FIBO Edit): 1-20. Higher = more dramatic style change.
* Negative Prompt (FIBO Edit): Exclude unwanted elements.
* Structure Influence (Legacy): 0.0-1.0. Preserves composition.
* Generation Steps: 0 = default. FIBO Edit supports up to 100.
* Seed: For reproducible results (0 = random).
* Use Cache: Avoid redundant API calls for same input/prompt.

== Requirements ==
Bria API token must be configured.
"""
    hda_definition.setComment(help_text)

    # Save
    print("\nStep 5: Saving HDA...")
    hda_definition.save(HDA_FILE)

    if os.path.exists(HDA_FILE):
        size = os.path.getsize(HDA_FILE)
        print(f"  Saved: {HDA_FILE} ({size} bytes)")
    else:
        print("  ERROR: File not created!")
        return False

    # Install
    print("\nStep 6: Installing...")
    hou.hda.installFile(HDA_FILE)

    # Verify
    obj_cat = hou.objNodeTypeCategory()
    if HDA_NAME in obj_cat.nodeTypes():
        print(f"  SUCCESS: '{HDA_NAME}' is available!")
    else:
        print(f"  WARNING: Node may not appear until Houdini restart")

    # Cleanup
    print("\nStep 7: Cleanup...")
    hda_node.destroy()
    print("  Done")

    print("\n" + "=" * 60)
    print("BUILD COMPLETE!")
    print("=" * 60)
    print(f"\nTo use:")
    print(f"  1. Create node: Tab > search 'bria_viewport_restyle'")
    print(f"  2. Click 'Create Render Camera' to save viewport")
    print(f"  3. Enter a style prompt (e.g., 'watercolor painting')")
    print(f"  4. Click 'Restyle Viewport' - result opens in MPlay")
    print(f"  5. Go to 'Apply Texture' tab to project onto geometry")
    print(f"  6. Use 'Expand and Apply' for more camera freedom")

    return True


# Run
if __name__ == "__main__" or True:
    try:
        build_hda()
    except Exception as e:
        print(f"\nBUILD FAILED: {e}")
        import traceback
        traceback.print_exc()
