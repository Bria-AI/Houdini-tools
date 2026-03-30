"""
Bria Background Replace HDA Builder Script for Houdini 21+ / Copernicus

Run in Houdini Python Shell:
    exec(open("<repo>/bria_houdini/builders/build_bg_replace_hda.py").read())
"""

import hou
import os

# Resolve repo root relative to this script's location.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else None
if _THIS_DIR:
    _REPO_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", ".."))
else:
    _REPO_ROOT = os.environ.get("BRIA_HOUDINI_REPO", os.getcwd())

# Configuration
HDA_NAME = "bria_bg_replace"
HDA_LABEL = "Bria BG Replace"
HDA_VERSION = "1.2.0"
HDA_FILE = os.path.join(_REPO_ROOT, "hda", "bria_bg_replace.hda")

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


def get_replace_bg_callback():
    """The callback script for the Replace Background button."""
    return '''
import hou
import numpy as np
from PIL import Image
import os
import tempfile

def run_replace_bg(node):
    # Get input
    inputs = node.inputs()
    if not inputs or inputs[0] is None:
        hou.ui.displayMessage("No input connected!", title="Bria Error")
        raise hou.NodeError("No input connected")

    input_cop = inputs[0]

    # Check if enabled
    if not node.evalParm("enable"):
        hou.ui.displayMessage("Node is disabled", title="Bria")
        return

    # Get prompt
    use_solid = node.evalParm("use_solid_color")
    if use_solid:
        bg_color_r = node.evalParm("bg_colorr")
        bg_color_g = node.evalParm("bg_colorg")
        bg_color_b = node.evalParm("bg_colorb")
        # Convert to hex
        bg_color = "#{:02x}{:02x}{:02x}".format(
            int(bg_color_r * 255),
            int(bg_color_g * 255),
            int(bg_color_b * 255)
        )
        prompt = ""
    else:
        prompt = node.evalParm("prompt")
        bg_color = None
        if not prompt.strip():
            hou.ui.displayMessage("Please enter a prompt describing the new background.", title="Bria Error")
            return

    # Get resolution
    width, height = input_cop.xRes(), input_cop.yRes()
    if width == 0 or height == 0:
        hou.ui.displayMessage("Invalid input resolution", title="Bria Error")
        raise hou.NodeError("Invalid input resolution")

    # Update status
    node.parm("status").set("Processing...")

    try:
        # Get input pixels
        pixels = input_cop.allPixelsAsString("C")

        # Import and run processor
        from bria_copernicus.nodes.bg_replace import get_processor

        processor = get_processor()
        use_cache = node.evalParm("use_cache")
        content_mod = node.evalParm("content_moderation")

        # Get generation mode
        mode_idx = node.evalParm("gen_mode")
        mode_map = {0: "fast", 1: "base", 2: "high_control"}
        mode = mode_map.get(mode_idx, "fast")

        # Get original quality setting
        original_quality = node.evalParm("original_quality")

        # Get negative prompt
        neg_prompt = node.evalParm("negative_prompt")
        neg_prompt = neg_prompt.strip() if neg_prompt else None

        # Get seed (0 means random)
        seed_val = node.evalParm("seed")
        seed = seed_val if seed_val > 0 else None

        # Get num_results
        num_results_idx = node.evalParm("num_results")
        num_results = num_results_idx + 1  # Menu is 0-indexed

        rgb_result, alpha_result = processor.process(
            input_pixels=pixels,
            width=width,
            height=height,
            prompt=prompt,
            bg_color=bg_color,
            mode=mode,
            original_quality=original_quality,
            negative_prompt=neg_prompt,
            seed=seed,
            num_results=num_results,
            channels=3,
            use_cache=use_cache,
            content_moderation=content_mod
        )

        if rgb_result is None or alpha_result is None:
            error = processor.get_error() or "Processing failed"
            node.parm("status").set("Error")
            hou.ui.displayMessage(error, title="Bria Error")
            raise hou.NodeError(error)

        # Combine into RGBA
        rgba = np.zeros((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = rgb_result
        rgba[:, :, 3] = alpha_result

        # Apply color space conversion based on setting
        colorspace = node.evalParm("colorspace")
        if colorspace == 0:  # sRGB (Display)
            from bria_copernicus.core.utils import linear_to_srgb
            rgba[:, :, :3] = linear_to_srgb(rgba[:, :, :3])

        # Convert and save
        rgba_8bit = (np.clip(np.flipud(rgba), 0, 1) * 255).astype(np.uint8)

        # Use node-specific temp file
        temp_dir = os.path.join(tempfile.gettempdir(), "bria_copernicus")
        os.makedirs(temp_dir, exist_ok=True)
        node_id = node.sessionId()
        temp_path = os.path.join(temp_dir, f"replace_{node_id}.png")

        Image.fromarray(rgba_8bit, "RGBA").save(temp_path)

        # Store path for the file node to use
        node.parm("result_path").set(temp_path)

        # Update internal file node - need to unlock first
        node.allowEditingOfContents()
        file_node = node.node("file_result")
        if file_node:
            # Try different parameter names for filename
            for pname in ["filename1", "file", "filename"]:
                fp = file_node.parm(pname)
                if fp:
                    fp.set(temp_path)
                    break
            # Try to reload
            reload_parm = file_node.parm("reload")
            if reload_parm:
                reload_parm.pressButton()
        # Don't call matchCurrentDefinition() - it would revert our file path change

        # Update status
        status_msg = "Done (cached)" if processor._last_status == "Cached" else "Done"
        node.parm("status").set(status_msg)

    except ImportError as e:
        node.parm("status").set("Import Error")
        hou.ui.displayMessage(f"Could not import bria_copernicus:\\n{e}\\n\\nMake sure the package is installed.", title="Bria Error")
        raise hou.NodeError(str(e))
    except Exception as e:
        node.parm("status").set("Error")
        hou.ui.displayMessage(str(e), title="Bria Error")
        raise hou.NodeError(str(e))

run_replace_bg(kwargs["node"])
'''


def build_hda():
    """Build the Bria BG Replace HDA."""

    print("=" * 50)
    print("Bria BG Replace HDA Builder v1.2")
    print("=" * 50)

    # Remove existing HDA
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

    # Create temp network
    print("\nStep 1: Creating temporary network...")
    obj = hou.node("/obj")

    temp_net = obj.node("_bria_builder_temp")
    if temp_net:
        temp_net.destroy()

    cop_net = obj.createNode("cop2net", "_bria_builder_temp")
    print(f"  Created: {cop_net.path()}")

    # Create subnet
    print("\nStep 2: Creating subnet structure...")
    subnet = cop_net.createNode("subnet", "bria_proto")

    # Internal nodes
    input_null = subnet.createNode("null", "INPUT")
    input_null.setInput(0, subnet.indirectInputs()[0])
    input_null.setPosition(hou.Vector2(0, 0))

    file_cop = subnet.createNode("file", "file_result")
    if file_cop is None:
        raise Exception("Could not create 'file' COP node")
    file_cop.setPosition(hou.Vector2(0, -2))

    # Try to find the filename parameter
    filename_parm = file_cop.parm("filename1") or file_cop.parm("file") or file_cop.parm("filename")
    if filename_parm:
        filename_parm.set("")

    output_null = subnet.createNode("null", "OUTPUT")
    output_null.setInput(0, file_cop)
    output_null.setPosition(hou.Vector2(0, -4))
    output_null.setDisplayFlag(True)
    output_null.setRenderFlag(True)

    subnet.layoutChildren()
    print("  Created: INPUT -> file_result -> OUTPUT")

    # Create HDA
    print(f"\nStep 3: Creating HDA...")

    hda_node = subnet.createDigitalAsset(
        name=HDA_NAME,
        hda_file_name=HDA_FILE,
        description=HDA_LABEL,
        min_num_inputs=1,
        max_num_inputs=1,
        version=HDA_VERSION
    )

    print(f"  Created: {hda_node.type().name()}")

    hda_def = hda_node.type().definition()

    # Build parameters
    print("\nStep 4: Adding parameters...")
    ptg = hou.ParmTemplateGroup()

    # === API KEY TAB (first for discoverability) ===
    ptg.append(build_api_key_tab())

    # === MAIN TAB ===
    main_folder = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    # Enable toggle
    enable = hou.ToggleParmTemplate("enable", "Enable", default_value=True)
    main_folder.addParmTemplate(enable)

    # Separator
    main_folder.addParmTemplate(hou.SeparatorParmTemplate("sep1"))

    # Prompt text field
    prompt = hou.StringParmTemplate(
        "prompt", "Prompt", 1,
        default_value=[""],
        string_type=hou.stringParmType.Regular
    )
    prompt.setHelp("Describe the new background (e.g., 'tropical beach at sunset')")
    prompt.setTags({"editor": "1"})  # Makes it multi-line
    main_folder.addParmTemplate(prompt)

    # Separator
    main_folder.addParmTemplate(hou.SeparatorParmTemplate("sep2"))

    # Use solid color toggle
    use_solid = hou.ToggleParmTemplate("use_solid_color", "Use Solid Color", default_value=False)
    use_solid.setHelp("Use a solid color instead of AI-generated background")
    main_folder.addParmTemplate(use_solid)

    # Background color picker
    bg_color = hou.FloatParmTemplate(
        "bg_color", "Background Color", 3,
        default_value=(0.5, 0.5, 0.5),
        min=0.0, max=1.0,
        naming_scheme=hou.parmNamingScheme.RGBA
    )
    bg_color.setHelp("Solid background color (when Use Solid Color is enabled)")
    main_folder.addParmTemplate(bg_color)

    # Separator
    main_folder.addParmTemplate(hou.SeparatorParmTemplate("sep3"))

    # Generation mode menu
    gen_mode = hou.MenuParmTemplate(
        "gen_mode", "Mode",
        menu_items=["fast", "base", "high_control"],
        menu_labels=["Fast", "Base", "High Control (Best Prompt Adherence)"],
        default_value=0
    )
    gen_mode.setHelp("Generation mode.\nFast: quickest, good for previews.\nBase: balanced quality.\nHigh Control: best prompt adherence, highest quality.")
    main_folder.addParmTemplate(gen_mode)

    # Negative prompt
    neg_prompt = hou.StringParmTemplate(
        "negative_prompt", "Negative Prompt", 1,
        default_value=[""],
        string_type=hou.stringParmType.Regular
    )
    neg_prompt.setHelp("Elements to exclude from the generated background (not available in Fast mode)")
    neg_prompt.setTags({"editor": "1"})
    neg_prompt.setConditional(hou.parmCondType.DisableWhen, "{ gen_mode == 0 }")
    main_folder.addParmTemplate(neg_prompt)

    # Seed
    seed_parm = hou.IntParmTemplate(
        "seed", "Seed", 1,
        default_value=[0],
        min=0, max=2147483647,
        min_is_strict=True
    )
    seed_parm.setHelp("Random seed for reproducible results (0 = random)")
    main_folder.addParmTemplate(seed_parm)

    # Num results
    num_results = hou.MenuParmTemplate(
        "num_results", "Num Results",
        menu_items=["1", "2", "3", "4"],
        menu_labels=["1", "2", "3", "4"],
        default_value=0
    )
    num_results.setHelp("Number of result variations to generate per API call (1-4)")
    main_folder.addParmTemplate(num_results)

    # Separator
    main_folder.addParmTemplate(hou.SeparatorParmTemplate("sep4"))

    # REPLACE BACKGROUND BUTTON
    replace_btn = hou.ButtonParmTemplate(
        "replace_background", "Replace Background",
        script_callback=get_replace_bg_callback(),
        script_callback_language=hou.scriptLanguage.Python
    )
    replace_btn.setHelp("Click to replace background using Bria AI")
    replace_btn.setTags({"button_icon": "COP2_colormap"})
    main_folder.addParmTemplate(replace_btn)

    # Status display
    status = hou.StringParmTemplate(
        "status", "Status", 1,
        default_value=["Ready"]
    )
    status.setHelp("Current processing status")
    main_folder.addParmTemplate(status)

    ptg.append(main_folder)

    # === SETTINGS TAB ===
    settings_folder = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)

    # Use cache
    use_cache = hou.ToggleParmTemplate("use_cache", "Use Cache", default_value=True)
    use_cache.setHelp("Cache results to avoid redundant API calls")
    settings_folder.addParmTemplate(use_cache)

    # Original quality
    original_quality = hou.ToggleParmTemplate("original_quality", "Original Quality", default_value=True)
    original_quality.setHelp("Preserve original image resolution.\nWhen OFF, output is downscaled to 1MP.")
    settings_folder.addParmTemplate(original_quality)

    # Content moderation
    content_mod = hou.ToggleParmTemplate("content_moderation", "Content Moderation", default_value=True)
    content_mod.setHelp("Enable Bria content moderation")
    settings_folder.addParmTemplate(content_mod)

    # Color space
    colorspace = hou.MenuParmTemplate(
        "colorspace", "Output Color Space",
        menu_items=["srgb", "linear"],
        menu_labels=["sRGB (Display)", "Linear (Compositing)"],
        default_value=0
    )
    colorspace.setHelp("sRGB for direct viewing, Linear for further compositing")
    settings_folder.addParmTemplate(colorspace)

    # Hidden result path (used internally)
    result_path = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    result_path.hide(True)
    settings_folder.addParmTemplate(result_path)

    ptg.append(settings_folder)

    # === INFO TAB ===
    info_folder = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)

    info_label = hou.LabelParmTemplate(
        "info_label", "Info",
        column_labels=["Bria BG Replace v" + HDA_VERSION]
    )
    info_folder.addParmTemplate(info_label)

    info_text = hou.LabelParmTemplate(
        "info_text", "",
        column_labels=["Replaces background using Bria AI"]
    )
    info_folder.addParmTemplate(info_text)

    info_text2 = hou.LabelParmTemplate(
        "info_text2", "",
        column_labels=["Enter a text prompt to describe the new background"]
    )
    info_folder.addParmTemplate(info_text2)

    ptg.append(info_folder)

    # Apply parameters
    hda_def.setParmTemplateGroup(ptg)
    print("  Parameters added")

    # Set icon
    try:
        hda_def.setIcon("COP2_colormap")
    except:
        pass

    # Set help
    help_text = """= Bria Background Replace =

Replaces image background using Bria's AI with a text prompt.

== Usage ==
1. Connect an image input
2. Enter a prompt describing the new background
   (e.g., "modern office with large windows")
3. Click "Replace Background" button
4. Wait for processing to complete

== Options ==
- Use Solid Color: Replace with a solid color instead of AI background
- Background Color: Pick the solid color to use

== Output ==
RGB image with the new AI-generated background.

== Requirements ==
Bria API token must be configured.
"""
    hda_def.setComment(help_text)

    # Set event scripts for auto-loading API key state
    print("  Adding event scripts...")
    python_module = '''
def refresh_key(kwargs):
    try:
        from bria_copernicus.ui.hda_api_key import refresh_api_key_state
        refresh_api_key_state(kwargs["node"])
    except Exception:
        pass
'''
    hda_def.addSection("PythonModule", python_module)
    event_handler = "kwargs['node'].hdaModule().refresh_key(kwargs)"
    hda_def.addSection("OnCreated", event_handler)
    hda_def.addSection("OnLoaded", event_handler)
    try:
        hda_def.setExtraFileOption("OnCreated/IsPython", True)
        hda_def.setExtraFileOption("OnLoaded/IsPython", True)
    except AttributeError:
        pass

    # Save
    print("\nStep 5: Saving HDA...")
    hda_def.save(HDA_FILE)

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
    cop_cat = hou.cop2NodeTypeCategory()
    if HDA_NAME in cop_cat.nodeTypes():
        print(f"  SUCCESS: '{HDA_NAME}' is available!")
    else:
        print(f"  WARNING: Node not found in COP category")

    # Cleanup
    print("\nStep 7: Cleanup...")
    cop_net.destroy()
    print("  Done")

    print("\n" + "=" * 50)
    print("BUILD COMPLETE!")
    print("=" * 50)
    print(f"\nTo use:")
    print(f"  1. Tab > search 'bria_bg_replace'")
    print(f"  2. Connect an image input")
    print(f"  3. Enter a prompt (e.g., 'sunset beach')")
    print(f"  4. Click 'Replace Background'")

    return True


# Run
if __name__ == "__main__" or True:
    try:
        build_hda()
    except Exception as e:
        print(f"\nBUILD FAILED: {e}")
        import traceback
        traceback.print_exc()
