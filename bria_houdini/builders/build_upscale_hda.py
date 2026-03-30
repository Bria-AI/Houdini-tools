"""
Bria Upscale HDA Builder Script for Houdini 21+ / Copernicus

Run in Houdini Python Shell:
    exec(open("<repo>/bria_houdini/builders/build_upscale_hda.py").read())
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
HDA_NAME = "bria_upscale"
HDA_LABEL = "Bria Upscale"
HDA_VERSION = "1.2.0"
HDA_FILE = os.path.join(_REPO_ROOT, "hda", "bria_upscale.hda")

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


def get_upscale_callback():
    """The callback script for the Upscale button."""
    return '''
import hou
import numpy as np
from PIL import Image
import os
import tempfile

def run_upscale(node):
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

    # Get scale factor
    scale_idx = node.evalParm("scale")
    scale = 2 if scale_idx == 0 else 4

    # Get resolution
    width, height = input_cop.xRes(), input_cop.yRes()
    if width == 0 or height == 0:
        hou.ui.displayMessage("Invalid input resolution", title="Bria Error")
        raise hou.NodeError("Invalid input resolution")

    # Check output size limit
    new_width = width * scale
    new_height = height * scale
    if new_width > 8192 or new_height > 8192:
        hou.ui.displayMessage(f"Output would exceed 8192px limit ({new_width}x{new_height})", title="Bria Error")
        raise hou.NodeError("Output too large")

    # Update status
    node.parm("status").set(f"Upscaling {scale}x...")

    try:
        # Get input pixels
        pixels = input_cop.allPixelsAsString("C")

        # Import and run processor
        from bria_copernicus.nodes.upscale import get_processor

        processor = get_processor()
        use_cache = node.evalParm("use_cache")
        preserve_alpha = node.evalParm("preserve_alpha")
        content_mod = node.evalParm("content_moderation")

        rgb_result, result_width, result_height = processor.process(
            input_pixels=pixels,
            width=width,
            height=height,
            scale=scale,
            preserve_alpha=preserve_alpha,
            channels=3,
            use_cache=use_cache,
            content_moderation=content_mod
        )

        if rgb_result is None:
            error = processor.get_error() or "Processing failed"
            node.parm("status").set("Error")
            hou.ui.displayMessage(error, title="Bria Error")
            raise hou.NodeError(error)

        # Apply color space conversion based on setting
        colorspace = node.evalParm("colorspace")
        if colorspace == 0:  # sRGB (Display)
            from bria_copernicus.core.utils import linear_to_srgb
            rgb_result = linear_to_srgb(rgb_result)

        # Convert and save (flip for standard image orientation)
        rgb_8bit = (np.clip(np.flipud(rgb_result), 0, 1) * 255).astype(np.uint8)

        # Use node-specific temp file
        temp_dir = os.path.join(tempfile.gettempdir(), "bria_copernicus")
        os.makedirs(temp_dir, exist_ok=True)
        node_id = node.sessionId()
        temp_path = os.path.join(temp_dir, f"upscale_{node_id}.png")

        Image.fromarray(rgb_8bit, "RGB").save(temp_path)

        # Store path for the file node to use
        node.parm("result_path").set(temp_path)

        # Update internal file node
        node.allowEditingOfContents()
        file_node = node.node("file_result")
        if file_node:
            for pname in ["filename1", "file", "filename"]:
                fp = file_node.parm(pname)
                if fp:
                    fp.set(temp_path)
                    break
            reload_parm = file_node.parm("reload")
            if reload_parm:
                reload_parm.pressButton()

        # Update status
        status_msg = "Done (cached)" if processor._last_status == "Cached" else f"Done ({result_width}x{result_height})"
        node.parm("status").set(status_msg)

    except ImportError as e:
        node.parm("status").set("Import Error")
        hou.ui.displayMessage(f"Could not import bria_copernicus:\\n{e}\\n\\nMake sure the package is installed.", title="Bria Error")
        raise hou.NodeError(str(e))
    except Exception as e:
        node.parm("status").set("Error")
        hou.ui.displayMessage(str(e), title="Bria Error")
        raise hou.NodeError(str(e))

run_upscale(kwargs["node"])
'''


def build_hda():
    """Build the Bria Upscale HDA."""

    print("=" * 50)
    print("Bria Upscale HDA Builder v1.2")
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

    # Scale menu
    scale = hou.MenuParmTemplate(
        "scale", "Scale",
        menu_items=["2", "4"],
        menu_labels=["2x", "4x"],
        default_value=0
    )
    scale.setHelp("Resolution multiplier (max output 8192x8192)")
    main_folder.addParmTemplate(scale)

    # Separator
    main_folder.addParmTemplate(hou.SeparatorParmTemplate("sep2"))

    # UPSCALE BUTTON
    upscale_btn = hou.ButtonParmTemplate(
        "upscale", "Upscale",
        script_callback=get_upscale_callback(),
        script_callback_language=hou.scriptLanguage.Python
    )
    upscale_btn.setHelp("Click to upscale image using Bria AI")
    upscale_btn.setTags({"button_icon": "COP2_scale"})
    main_folder.addParmTemplate(upscale_btn)

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

    # Preserve alpha
    preserve_alpha = hou.ToggleParmTemplate("preserve_alpha", "Preserve Alpha", default_value=True)
    preserve_alpha.setHelp("Preserve alpha channel in RGBA input images")
    settings_folder.addParmTemplate(preserve_alpha)

    # Content moderation
    content_mod = hou.ToggleParmTemplate("content_moderation", "Content Moderation", default_value=True)
    content_mod.setHelp("Enable Bria content moderation")
    settings_folder.addParmTemplate(content_mod)

    # Separator
    settings_folder.addParmTemplate(hou.SeparatorParmTemplate("sep_settings"))

    # Use cache
    use_cache = hou.ToggleParmTemplate("use_cache", "Use Cache", default_value=True)
    use_cache.setHelp("Cache results to avoid redundant API calls")
    settings_folder.addParmTemplate(use_cache)

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
        column_labels=["Bria Upscale v" + HDA_VERSION]
    )
    info_folder.addParmTemplate(info_label)

    info_text = hou.LabelParmTemplate(
        "info_text", "",
        column_labels=["Increases image resolution using Bria AI"]
    )
    info_folder.addParmTemplate(info_text)

    info_text2 = hou.LabelParmTemplate(
        "info_text2", "",
        column_labels=["Maximum output: 8192x8192 pixels"]
    )
    info_folder.addParmTemplate(info_text2)

    ptg.append(info_folder)

    # Apply parameters
    hda_def.setParmTemplateGroup(ptg)
    print("  Parameters added")

    # Set icon
    try:
        hda_def.setIcon("COP2_scale")
    except:
        pass

    # Set help
    help_text = """= Bria Upscale =

Increases image resolution using Bria's AI upscaling model.

== Usage ==
1. Connect an image input
2. Select scale factor (2x or 4x)
3. Click "Upscale" button
4. Wait for processing to complete

== Limits ==
Maximum output resolution is 8192x8192 pixels.

== Output ==
RGB image at increased resolution.

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
    print(f"  1. Tab > search 'bria_upscale'")
    print(f"  2. Connect an image input")
    print(f"  3. Select 2x or 4x scale")
    print(f"  4. Click 'Upscale'")

    return True


# Run
if __name__ == "__main__" or True:
    try:
        build_hda()
    except Exception as e:
        print(f"\nBUILD FAILED: {e}")
        import traceback
        traceback.print_exc()
