"""
Bria New HDA Builder — builds all 4 new COP HDAs in one shot.

  1. Bria Enhancer
  2. Bria FIBO Edit Recipes
  3. Bria Generate Structured Prompt
  4. Bria FIBO Generate

Run in Houdini Python Shell:
    exec(open("<repo>/bria_houdini/builders/build_new_hdas.py").read())
"""

import hou
import os
import textwrap

# Resolve repo root relative to this script's location.
# When run via exec(open("<repo>/bria_houdini/builders/build_new_hdas.py").read()),
# __file__ is not set, so we fall back to BRIA_HOUDINI_REPO env var or auto-detect
# from the known directory structure (this file lives at <repo>/bria_houdini/builders/).
def _find_repo_root():
    # 1) Direct execution — __file__ is set correctly
    if "__file__" in dir() and os.path.basename(__file__) == "build_new_hdas.py":
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    # 2) Env var override
    env = os.environ.get("BRIA_HOUDINI_REPO")
    if env and os.path.isdir(env):
        return env
    # 3) Auto-detect: walk up from cwd looking for bria_houdini/builders/build_new_hdas.py
    for candidate in [os.getcwd(), os.path.expanduser("~/Desktop/Houdini_Tool_Release"),
                      os.path.expanduser("~/Desktop/Bria_Dev/bria-houdini")]:
        if os.path.isfile(os.path.join(candidate, "bria_houdini", "builders", "build_new_hdas.py")):
            return candidate
    return os.getcwd()

_REPO_ROOT = _find_repo_root()

HDAS_DIR = os.path.join(_REPO_ROOT, "bria_houdini", "otls")
PYMOD_DIR = os.path.join(_REPO_ROOT, "bria_houdini", "pythonmodules")

os.makedirs(HDAS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _set_tool_submenu(hda_def, submenu):
    """Set TAB menu submenu for an HDA using Houdini's defaulttools module.

    This is the canonical way to programmatically set TAB menu categories.
    Houdini's defaulttools module generates proper Tools.shelf XML with
    correct CDATA wrapping and $HDA_* variable substitution.
    """
    import defaulttools
    import tempfile

    node_type = hda_def.nodeType()
    tool_name = hou.shelves.defaultToolName(
        node_type.category().name(), node_type.name()
    )

    # Remove any existing tool registration to avoid conflicts
    existing = hou.shelves.tools().get(tool_name)
    if existing:
        existing.destroy()

    # Generate proper Tools.shelf XML via Houdini's internal module
    temp_file = os.path.join(tempfile.gettempdir(), "bria_temp.shelf")
    try:
        tool = defaulttools.createDefaultHDATool(
            temp_file, node_type, tool_name,
            locations=(submenu,),
        )
        defaulttools.setHDAToolVariables(tool, hda_def)
        contents = hou.readFile(temp_file)
        hda_def.addSection("Tools.shelf", contents)
        print(f"  TAB menu: '{submenu}' (via defaulttools)")
    finally:
        # Cleanup temp file and phantom tool
        if os.path.exists(temp_file):
            os.remove(temp_file)
        phantom = hou.shelves.tools().get("$HDA_DEFAULT_TOOL")
        if phantom:
            phantom.destroy()


def _remove_existing(hda_file, base_name=None):
    """Remove an HDA file and uninstall all definitions from it.

    If base_name is provided, also uninstall any matching definitions
    from other files (handles renamed/versioned duplicates).
    """
    if os.path.exists(hda_file):
        try:
            hou.hda.uninstallFile(hda_file)
        except Exception:
            pass
        try:
            for defn in hou.hda.definitionsInFile(hda_file):
                defn.destroy()
        except Exception:
            pass
        try:
            os.remove(hda_file)
        except Exception:
            pass

    # Clean up any lingering definitions with the same base name
    if base_name:
        cop_cat = hou.nodeTypeCategories().get("Cop")
        if cop_cat:
            for type_name in list(cop_cat.nodeTypes().keys()):
                if base_name in type_name:
                    try:
                        node_type = cop_cat.nodeTypes()[type_name]
                        for defn in node_type.allInstalledDefinitions():
                            print(f"  Uninstalling old definition: {type_name} from {defn.libraryFilePath()}")
                            defn.destroy()
                    except Exception:
                        pass


def _build_cop_hda(name, label, version, hda_file, min_inputs=None, max_inputs=None, num_inputs=1):
    """Create a Copernicus (Cop) HDA matching the working HDA structure.

    Internal structure (mirrors bria_expand):
        inputs ──► switch_result input1  (pass-through)
        loader_result ──► switch_result input2  (API result)
        switch_result ──► outputs
        rop_save_input  (ROP for exporting input to disk)

    For optional inputs, pass min_inputs=0, max_inputs=1.
    """
    # Support both old num_inputs and new min/max style
    if min_inputs is None:
        min_inputs = num_inputs
    if max_inputs is None:
        max_inputs = num_inputs

    obj = hou.node("/obj")

    # Clean up any leftover temp nodes
    temp = obj.node("_bria_builder_temp")
    if temp:
        temp.destroy()

    # Use copnet (Copernicus) instead of cop2net (legacy COP2)
    cop_net = obj.createNode("copnet", "_bria_builder_temp")
    subnet = cop_net.createNode("subnet", "bria_proto")

    # Configure Copernicus subnet to expose multiple input ports.
    # The subnet's Inputs multiparm controls how many connectors appear.
    if max_inputs > 1:
        _set_inputs = False
        for parm_name in ("numinputs", "inputs"):
            p = subnet.parm(parm_name)
            if p is not None:
                p.set(max_inputs)
                print(f"  Set subnet {parm_name}={max_inputs}")
                _set_inputs = True
                break
        if not _set_inputs:
            # Diagnostic: dump all parms so we can find the right one
            print(f"  WARNING: Could not find subnet input count parm. Available parms:")
            for p in subnet.parms():
                if "input" in p.name().lower():
                    print(f"    {p.name()} = {p.eval()}")

    # Create internal nodes (no wiring yet — wiring doesn't survive createDigitalAsset)
    subnet.createNode("file", "loader_result").setPosition(hou.Vector2(4, -3))
    subnet.createNode("switch", "switch_result").setPosition(hou.Vector2(8, 0))

    # NOTE: rop_save_input is created in _wire_internals() after createDigitalAsset,
    # because rop_image type is only available inside an HDA context, not a plain subnet.

    subnet.layoutChildren()

    # Use bria:: namespace to match existing HDAs (e.g., bria::bria_expand::1.0)
    namespaced_name = f"bria::{name}::{version}"

    hda_node = subnet.createDigitalAsset(
        name=namespaced_name,
        hda_file_name=hda_file,
        description=label,
        min_num_inputs=min_inputs,
        max_num_inputs=max_inputs,
        version=version,
    )

    return hda_node, cop_net


def _add_advanced_folder(ptg):
    """Add shared advanced/connection parms (hidden by default)."""
    adv = hou.FolderParmTemplate("advanced", "Advanced", folder_type=hou.folderType.Tabs)

    adv.addParmTemplate(hou.StringParmTemplate("api_token", "API Token (deprecated)", 1, default_value=[""]))
    adv.addParmTemplate(hou.StringParmTemplate("api_base_url", "API Base URL", 1, default_value=[""]))
    adv.addParmTemplate(hou.ToggleParmTemplate("use_bearer_auth", "Use Bearer Auth", default_value=False))
    adv.addParmTemplate(hou.SeparatorParmTemplate("adv_sep1"))
    adv.addParmTemplate(hou.ToggleParmTemplate("use_env_proxy", "Use Env Proxy", default_value=False))
    adv.addParmTemplate(hou.StringParmTemplate("http_proxy", "HTTP Proxy", 1, default_value=[""]))
    adv.addParmTemplate(hou.StringParmTemplate("https_proxy", "HTTPS Proxy", 1, default_value=[""]))

    adv.hide(True)
    ptg.append(adv)


def _load_pymodule(filename):
    """Load a PythonModule file from the pythonmodules directory."""
    path = os.path.join(PYMOD_DIR, filename)
    with open(path, "r") as f:
        return f.read()


def _build_vgl_editor_tab(generate_callback=None, generate_label="Generate",
                          tab_label="VGL Editor", disable_condition=None,
                          show_refresh_upstream=True):
    """Build the VGL Editor / Structured Prompt tab.

    Used by FIBO Generate, FIBO Edit, FIBO Edit Recipes, and Viewport Render.
    Field definitions must stay in sync with VGL_OBJECT_FIELDS etc. in vgl_utils.py.

    Args:
        generate_callback: Python callback string for the generate button (e.g.
            "hou.phm().on_generate_image(kwargs)"). If None, no button is added.
        generate_label: Label for the generate button.
        tab_label: Display label for the tab (e.g. "Structured Prompt").
        disable_condition: Optional DisableWhen expression (e.g.
            "{ use_structured_prompt == 0 }") applied to all content parms
            so they grey out when the mode is inactive.  The generate button
            is exempt so it always stays clickable.
        show_refresh_upstream: If True (default), include the "Refresh from
            Upstream" button. Set to False for nodes without COP inputs
            (e.g. Viewport Render).
    """
    vgl_tab = hou.FolderParmTemplate("vgl_editor", tab_label, folder_type=hou.folderType.Tabs)

    def _apply_disable(tmpl):
        """Apply the disable condition to a parm/folder template if set."""
        if disable_condition:
            tmpl.setConditional(hou.parmCondType.DisableWhen, disable_condition)
        return tmpl

    # Hidden parm: stores short_description for round-trip assembly
    short_desc = hou.StringParmTemplate("vgl_short_desc", "Short Description", 1, default_value=[""])
    short_desc.hide(True)
    vgl_tab.addParmTemplate(short_desc)

    # Description label (display-only)
    vgl_desc = hou.LabelParmTemplate("vgl_description", "Description:",
                                      column_labels=["(connect or paste VGL to see)"])
    vgl_tab.addParmTemplate(_apply_disable(vgl_desc))
    vgl_tab.addParmTemplate(hou.SeparatorParmTemplate("vgl_sep1"))

    # --- Scene & Background (collapsible, single multi-line text) ---
    scene_folder = hou.FolderParmTemplate("vgl_folder_scene", "Scene & Background",
                                           folder_type=hou.folderType.Collapsible)
    scene_parm = hou.StringParmTemplate("vgl_scene_text", "", 1, default_value=[""])
    scene_parm.setTags({"editor": "1", "editorLines": "3"})
    scene_folder.addParmTemplate(scene_parm)
    vgl_tab.addParmTemplate(_apply_disable(scene_folder))

    # --- Subjects (MultiparmBlock) ---
    # Object fields: (parm_suffix, label, is_person, field_type, multi_line)
    obj_fields = [
        ("desc",     "Description",   False, "str", True),
        ("loc",      "Location",      False, "str", False),
        ("shape",    "Shape & Color", False, "str", False),
        ("relsize",  "Relative Size", False, "str", False),
        ("appear",   "Appearance",    False, "str", True),
        ("tex",      "Texture",       False, "str", False),
        ("orient",   "Orientation",   False, "str", False),
        ("rel",      "Relationship",  False, "str", False),
        ("numobj",   "Count",         False, "int", False),
        # Person-specific (added to sub-folder below)
        ("action",   "Action",        True,  "str", False),
        ("pose",     "Pose",          True,  "str", False),
        ("gender",   "Gender",        True,  "str", False),
        ("expr",     "Expression",    True,  "str", False),
        ("clothing", "Clothing",      True,  "str", False),
        ("skin",     "Skin Tone",     True,  "str", False),
    ]

    obj_block = hou.FolderParmTemplate(
        "vgl_obj_count", "Objects",
        folder_type=hou.folderType.MultiparmBlock,
    )

    # Each instance wrapped in a collapsible folder
    obj_instance = hou.FolderParmTemplate("vgl_obj_folder_#", "Object #",
                                           folder_type=hou.folderType.Collapsible)

    # Standard object fields
    for suffix, label, is_person, ftype, multi_line in obj_fields:
        if is_person:
            continue
        if ftype == "int":
            parm = hou.IntParmTemplate(f"vgl_obj_{suffix}_#", label, 1,
                                        default_value=(0,), min=0, max=100)
        else:
            parm = hou.StringParmTemplate(f"vgl_obj_{suffix}_#", label, 1, default_value=[""])
            if multi_line:
                parm.setTags({"editor": "1", "editorLines": "2"})
        obj_instance.addParmTemplate(parm)

    # Person Details sub-folder (collapsed by default)
    person_folder = hou.FolderParmTemplate("vgl_obj_person_#", "Person Details",
                                            folder_type=hou.folderType.Collapsible)
    for suffix, label, is_person, ftype, multi_line in obj_fields:
        if not is_person:
            continue
        parm = hou.StringParmTemplate(f"vgl_obj_{suffix}_#", label, 1, default_value=[""])
        person_folder.addParmTemplate(parm)
    obj_instance.addParmTemplate(person_folder)

    obj_block.addParmTemplate(obj_instance)
    vgl_tab.addParmTemplate(_apply_disable(obj_block))

    # --- Lighting (collapsible, 3 individual fields) ---
    light_folder = hou.FolderParmTemplate("vgl_folder_lighting", "Lighting",
                                           folder_type=hou.folderType.Collapsible)
    for suffix, label in [("cond", "Conditions"), ("dir", "Direction"), ("shadows", "Shadows")]:
        parm = hou.StringParmTemplate(f"vgl_lighting_{suffix}", label, 1, default_value=[""])
        light_folder.addParmTemplate(parm)
    vgl_tab.addParmTemplate(_apply_disable(light_folder))

    # --- Aesthetics (collapsible, 3 individual fields) ---
    aes_folder = hou.FolderParmTemplate("vgl_folder_aesthetics", "Aesthetics",
                                         folder_type=hou.folderType.Collapsible)
    for suffix, label in [("colorscheme", "Color Scheme"), ("comp", "Composition"), ("mood", "Mood & Atmosphere")]:
        parm = hou.StringParmTemplate(f"vgl_aesthetics_{suffix}", label, 1, default_value=[""])
        aes_folder.addParmTemplate(parm)
    vgl_tab.addParmTemplate(_apply_disable(aes_folder))

    # --- Photographic (collapsible, 4 individual fields) ---
    photo_folder = hou.FolderParmTemplate("vgl_folder_photo", "Photographic",
                                           folder_type=hou.folderType.Collapsible)
    for suffix, label in [("camangle", "Camera Angle"), ("dof", "Depth of Field"),
                          ("focus", "Focus"), ("lens", "Lens / Focal Length")]:
        parm = hou.StringParmTemplate(f"vgl_photo_{suffix}", label, 1, default_value=[""])
        photo_folder.addParmTemplate(parm)
    vgl_tab.addParmTemplate(_apply_disable(photo_folder))

    # --- Style (collapsible, single field) ---
    style_folder = hou.FolderParmTemplate("vgl_folder_style", "Style",
                                           folder_type=hou.folderType.Collapsible)
    style_parm = hou.StringParmTemplate("vgl_style_text", "", 1, default_value=[""])
    style_folder.addParmTemplate(style_parm)
    vgl_tab.addParmTemplate(_apply_disable(style_folder))

    # --- Text Overlays (collapsible, raw JSON — usually empty) ---
    text_folder = hou.FolderParmTemplate("vgl_folder_text", "Text Overlays",
                                          folder_type=hou.folderType.Collapsible)
    text_parm = hou.StringParmTemplate("vgl_text_json", "", 1, default_value=[""])
    text_parm.setTags({"editor": "1", "editorLines": "4"})
    text_folder.addParmTemplate(text_parm)
    vgl_tab.addParmTemplate(_apply_disable(text_folder))

    # --- Other Fields (collapsible, raw JSON catch-all) ---
    other_folder = hou.FolderParmTemplate("vgl_folder_other", "Other Fields",
                                           folder_type=hou.folderType.Collapsible)
    other_parm = hou.StringParmTemplate("vgl_other", "", 1, default_value=[""])
    other_parm.setTags({"editor": "1", "editorLines": "4"})
    other_folder.addParmTemplate(other_parm)
    vgl_tab.addParmTemplate(_apply_disable(other_folder))

    vgl_tab.addParmTemplate(hou.SeparatorParmTemplate("vgl_sep2"))

    # --- Action buttons ---
    parse_btn = hou.ButtonParmTemplate(
        "parse_vgl", "Parse VGL from Raw JSON",
        script_callback="hou.phm().on_parse_vgl(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    vgl_tab.addParmTemplate(_apply_disable(parse_btn))

    if show_refresh_upstream:
        refresh_btn = hou.ButtonParmTemplate(
            "refresh_upstream", "Refresh from Upstream",
            script_callback="hou.phm().on_refresh_upstream(kwargs)",
            script_callback_language=hou.scriptLanguage.Python,
        )
        vgl_tab.addParmTemplate(_apply_disable(refresh_btn))

    # --- Generate button (same action as Main tab, for convenience) ---
    if generate_callback:
        gen_btn = hou.ButtonParmTemplate(
            "vgl_generate", generate_label,
            script_callback=generate_callback,
            script_callback_language=hou.scriptLanguage.Python,
        )
        vgl_tab.addParmTemplate(gen_btn)

    # --- Raw JSON (advanced, collapsible) ---
    raw_folder = hou.FolderParmTemplate("vgl_folder_raw", "Raw JSON (Advanced)",
                                         folder_type=hou.folderType.Collapsible)
    sp_parm = hou.StringParmTemplate("structured_prompt", "Full VGL JSON", 1, default_value=[""])
    sp_parm.setTags({"editor": "1", "editorLines": "12"})
    raw_folder.addParmTemplate(sp_parm)
    sync_btn = hou.ButtonParmTemplate(
        "sync_vgl_json", "Update JSON from Fields",
        script_callback="hou.phm().sync_vgl_to_json(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    raw_folder.addParmTemplate(sync_btn)
    vgl_tab.addParmTemplate(_apply_disable(raw_folder))

    return vgl_tab


def _build_history_tab():
    """Build a shared History tab for browsing and restoring previous results.

    Added to all Bria HDAs — dynamic menu shows past results with diff-based labels.
    """
    tab = hou.FolderParmTemplate("history", "History", folder_type=hou.folderType.Tabs)

    # Dynamic menu populated by result_history.build_history_menu()
    menu = hou.StringParmTemplate("result_history", "Result History", 1, default_value=[""])
    menu.setMenuType(hou.menuType.StringReplace)
    menu.setItemGeneratorScript("hou.phm().build_history_menu(kwargs)")
    menu.setItemGeneratorScriptLanguage(hou.scriptLanguage.Python)
    tab.addParmTemplate(menu)

    # Load button
    load_btn = hou.ButtonParmTemplate(
        "load_result", "Load Selected",
        script_callback="hou.phm().on_load_result(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    tab.addParmTemplate(load_btn)

    # Open folder button
    open_label = "Open in Finder" if __import__("platform").system() == "Darwin" else "Open in Explorer"
    open_btn = hou.ButtonParmTemplate(
        "open_result_folder", open_label,
        script_callback="hou.phm().on_open_result_folder(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    tab.addParmTemplate(open_btn)

    tab.addParmTemplate(hou.SeparatorParmTemplate("hist_sep1"))

    # Result count label
    count_label = hou.LabelParmTemplate("result_count", "Results:",
                                         column_labels=["(generate to see history)"])
    tab.addParmTemplate(count_label)

    return tab


def _wire_internals(hda_node, max_inputs):
    """Wire internal nodes AFTER createDigitalAsset (connections don't survive it)."""
    hda_node.allowEditingOfContents()

    loader = hda_node.node("loader_result")
    switch = hda_node.node("switch_result")
    cop_inputs = hda_node.node("inputs")
    cop_outputs = hda_node.node("outputs")
    # Create rop_save_input inside the HDA (rop_image type, matching Carlos's HDAs)
    rop = hda_node.node("rop_save_input")
    if rop is None and max_inputs > 0:
        for rop_type in ("rop_image", "rop_comp", "ropcomposite"):
            try:
                rop = hda_node.createNode(rop_type, "rop_save_input")
                if rop is not None:
                    rop.setPosition(hou.Vector2(0, -3))
                    print(f"  Created rop_save_input (type={rop_type})")
                    break
            except Exception as exc:
                print(f"  ROP type '{rop_type}' failed: {exc}")
                rop = None
        if rop is None:
            print(f"  WARNING: Could not create rop_save_input")

    if loader is not None:
        # Copernicus File node requires AOV config to load images
        if loader.parm("aovs") is not None:
            loader.parm("aovs").set(1)
        if loader.parm("aov1") is not None:
            loader.parm("aov1").set("C")
        # Set channel reference so loader reads from HDA's result_path parm.
        # This eliminates the need for allowEditingOfContents() at runtime.
        fp = loader.parm("filename") or loader.parm("filename1") or loader.parm("file")
        if fp:
            fp.setExpression('chs("../result_path")', hou.exprLanguage.Hscript)
        print(f"  Configured loader_result (aovs=1, aov1=C, filename -> chs result_path)")

    if switch is not None:
        if max_inputs > 0 and cop_inputs is not None:
            switch.setInput(0, cop_inputs)
            print(f"  Wired inputs -> switch_result input1")
        if loader is not None:
            switch.setInput(1, loader)
            print(f"  Wired loader_result -> switch_result input2")
        if cop_outputs is not None:
            # Disconnect the auto-wire (inputs -> outputs) first
            cop_outputs.setInput(0, None)
            cop_outputs.setInput(0, switch)
            print(f"  Wired switch_result -> outputs")
        # Set switch to auto-toggle based on whether result_path is populated.
        # 0 = pass-through (no result yet), 1 = show result.
        if switch.parm("input") is not None:
            switch.parm("input").setExpression('strlen(chs("../result_path")) > 0', hou.exprLanguage.Hscript)
            print(f"  Set switch_result expression -> auto-toggle on result_path")
    elif loader is not None and cop_outputs is not None:
        cop_outputs.setInput(0, None)
        cop_outputs.setInput(0, loader)
        print(f"  Wired loader_result -> outputs (no switch)")

    if rop is not None and cop_inputs is not None:
        rop.setInput(0, cop_inputs)
        rfp = rop.parm("copoutput") or rop.parm("sopoutput") or rop.parm("filename")
        if rfp:
            rfp.set("$HIPNAME.$OS.$F4.png")
        print(f"  Wired rop_save_input")

    # For 2-input nodes (erase, genfill), create rop_save_mask for the mask input
    if max_inputs >= 2:
        rop_mask = hda_node.node("rop_save_mask")
        if rop_mask is None:
            for rop_type in ("rop_image", "rop_comp", "ropcomposite"):
                try:
                    rop_mask = hda_node.createNode(rop_type, "rop_save_mask")
                    if rop_mask is not None:
                        rop_mask.setPosition(hou.Vector2(0, -6))
                        print(f"  Created rop_save_mask (type={rop_type})")
                        break
                except Exception:
                    rop_mask = None
        if rop_mask is not None and cop_inputs is not None:
            # Wire to output 1 of the inputs node (= HDA input 2 / mask).
            # Output 0 = input 1 (image), output 1 = input 2 (mask).
            rop_mask.setInput(0, cop_inputs, 1)
            rfp = rop_mask.parm("copoutput") or rop_mask.parm("sopoutput") or rop_mask.parm("filename")
            if rfp:
                rfp.set("$HIPNAME.$OS.mask.$F4.png")
            print(f"  Wired rop_save_mask")


def _finalize(hda_node, hda_def, hda_file, pymod_content, cop_net, name, max_inputs=1):
    """Wire internals, set PythonModule, save, install, cleanup."""
    _wire_internals(hda_node, max_inputs)

    hda_def.addSection("PythonModule", pymod_content)
    hda_def.setExtraFileOption("PythonModule/IsPython", True)

    # template_node=hda_node ensures node contents (including rop_save_input
    # created in _wire_internals via allowEditingOfContents) are captured.
    hda_def.save(hda_file, template_node=hda_node)
    hou.hda.installFile(hda_file)

    # Set input labels via the HDA's DialogScript section.
    if max_inputs >= 2:
        ds = hda_def.sections().get("DialogScript")
        if ds:
            content = ds.contents()
            lines = content.split("\n")
            # Find the "label" line and insert inputlabel directives after it
            insert_idx = None
            for i, line in enumerate(lines):
                if line.strip().startswith("label"):
                    insert_idx = i + 1
                    break
            if insert_idx is None:
                # Fallback: insert after opening brace
                for i, line in enumerate(lines):
                    if "{" in line:
                        insert_idx = i + 1
                        break
            if insert_idx is not None:
                label_lines = [
                    '    inputlabel\t1\t"Image"',
                    '    inputlabel\t2\t"Mask"',
                ]
                for j, ll in enumerate(label_lines):
                    lines.insert(insert_idx + j, ll)
                ds.setContents("\n".join(lines))
                print(f"  Set HDA input labels: Image, Mask (via DialogScript)")
            else:
                print(f"  WARNING: Could not find insertion point for input labels")

    # Set TAB menu category using Houdini's defaulttools module.
    # Must happen AFTER save+install so the node type is fully registered.
    _set_tool_submenu(hda_def, "Bria AI")
    hda_def.save(hda_file)
    hou.hda.installFile(hda_file)

    # Cleanup
    try:
        cop_net.destroy()
    except:
        pass

    if os.path.exists(hda_file):
        size = os.path.getsize(hda_file)
        # Verify it registered in the Cop (Copernicus) category
        cop_cat = hou.nodeTypeCategories().get("Cop")
        found = any(name in t for t in cop_cat.nodeTypes()) if cop_cat else False
        status = "Cop OK" if found else "CHECK CATEGORY"
        print(f"  OK: {name} -> {hda_file} ({size} bytes) [{status}]")
    else:
        print(f"  FAILED: {hda_file} not created!")


# ===================================================================
# 1. BRIA ENHANCER
# ===================================================================

def build_enhancer():
    print("\n--- Building Bria Enhancer ---")

    hda_file = os.path.join(HDAS_DIR, "bria_enhancer.hda")
    _remove_existing(hda_file)

    hda_node, cop_net = _build_cop_hda("bria_enhancer", "Bria Enhancer", "1.0.0", hda_file, num_inputs=1)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # --- Main tab ---
    main = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    main.addParmTemplate(hou.MenuParmTemplate(
        "resolution", "Resolution",
        menu_items=["1MP", "2MP", "4MP"],
        menu_labels=["1 Megapixel", "2 Megapixels", "4 Megapixels"],
        default_value=0,
    ))

    main.addParmTemplate(hou.SeparatorParmTemplate("sep1"))

    btn = hou.ButtonParmTemplate(
        "enhance", "Run Enhance",
        script_callback="hou.phm().on_enhancer(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(btn)

    ptg.append(main)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.ToggleParmTemplate("preserve_alpha", "Preserve Alpha", default_value=True))
    settings.addParmTemplate(hou.IntParmTemplate("steps_num", "Steps (10-50, 0 = default)", 1,
                                                  default_value=[0], min=0, max=50,
                                                  min_is_strict=True, max_is_strict=True))
    settings.addParmTemplate(hou.IntParmTemplate("seed", "Seed (0 = random)", 1, default_value=[0],
                                                  min=0, max=2147483647,
                                                  min_is_strict=True, max_is_strict=True))
    settings.addParmTemplate(hou.SeparatorParmTemplate("mod_sep"))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_input", "Content Moderation (Input)", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_output", "Content Moderation (Output)", default_value=False))
    ptg.append(settings)

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria Enhancer v1.1.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Enhance image quality using Bria AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP_shapescatter")
    except:
        pass

    pymod = _load_pymodule("bria_enhancer.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_enhancer")


# ===================================================================
# 2. BRIA FIBO EDIT PRESETS
# ===================================================================

def build_fibo_edit_recipes():
    print("\n--- Building Bria FIBO Edit Recipes v2 ---")

    # Preset menu data — inlined to avoid Houdini module-cache issues at build time.
    # Must stay in sync with CATEGORY_ORDER / PRESET_CATEGORIES in
    # bria_houdini/nodes/fibo_edit_recipes.py (the runtime source of truth).
    _CATEGORIES = [
        ("custom",       "Custom"),
        ("style",        "Style"),
        ("weather",      "Weather"),
        ("seasons",      "Seasons"),
        ("time_of_day",  "Time of Day"),
        ("camera",       "Camera"),
        ("lighting",     "Lighting"),
        ("compositing",  "Compositing"),
        ("clean",           "Clean / Artifacts"),
        ("ai_corrections",  "AI Corrections"),
        ("object_edits",    "Object Edits"),
    ]
    _PRESET_MENUS = {
        "style": [
            ("hand_drawn_classic",      "Hand-Drawn Classic"),
            ("3d_animated",             "3D Animated"),
            ("japanese_fantasy_anime",  "Japanese Fantasy Anime"),
            ("cel_shaded_anime",        "Cel-Shaded Anime"),
            ("film_noir",               "Film Noir"),
            ("aaa_game",                "AAA Game"),
            ("blockbuster_cinematic",   "Blockbuster Cinematic"),
            ("indie_film",              "Indie Film"),
            ("tv_sitcom",               "TV Sitcom"),
            ("oil_painting",            "Oil Painting"),
            ("watercolor",              "Watercolor"),
            ("comic_book",              "Comic Book"),
            ("pencil_sketch",           "Pencil Sketch"),
            ("retro_pixel",             "Retro Pixel Art"),
            ("cyberpunk",               "Cyberpunk"),
            ("steampunk",               "Steampunk"),
            ("pop_art",                 "Pop Art"),
            ("art_nouveau",             "Art Nouveau"),
        ],
        "weather": [
            ("sunny_clear",  "Sunny & Clear"),
            ("overcast",     "Overcast"),
            ("rainy",        "Rainy"),
            ("thunderstorm", "Thunderstorm"),
            ("snowy",        "Snowy"),
            ("foggy",        "Foggy / Misty"),
            ("windy",        "Windy"),
            ("hazy_humid",   "Hazy / Humid"),
        ],
        "seasons": [
            ("spring", "Spring"),
            ("summer", "Summer"),
            ("autumn", "Autumn"),
            ("winter", "Winter"),
        ],
        "time_of_day": [
            ("dawn",        "Dawn"),
            ("morning",     "Morning"),
            ("golden_hour", "Golden Hour"),
            ("midday",      "Midday"),
            ("blue_hour",   "Blue Hour"),
            ("dusk",        "Dusk"),
            ("night",       "Night"),
            ("starry_night","Starry Night"),
        ],
        "camera": [
            ("shallow_dof",   "Shallow Depth of Field"),
            ("tilt_shift",    "Tilt Shift"),
            ("wide_angle",    "Wide Angle"),
            ("macro_closeup", "Macro Close-Up"),
            ("birds_eye",     "Bird's Eye View"),
            ("dutch_angle",   "Dutch Angle"),
            ("long_exposure", "Long Exposure"),
            ("fisheye",       "Fisheye"),
        ],
        "lighting": [
            ("dramatic_side",      "Dramatic Side Light"),
            ("rim_backlight",      "Rim / Backlight"),
            ("soft_diffused",      "Soft Diffused"),
            ("neon_glow",          "Neon Glow"),
            ("candlelight",        "Candlelight"),
            ("studio_three_point", "Studio Three-Point"),
            ("volumetric_rays",    "Volumetric Rays"),
            ("harsh_flash",        "Harsh Flash"),
        ],
        "clean": [
            ("color_correction",            "Color Correction"),
            ("gamma_correction",            "Gamma Correction"),
            ("fix_artifacts",               "Fix Artifacts"),
            ("remove_noise",                "Remove Noise"),
            ("sharpen",                     "Sharpen"),
            ("fix_white_balance",           "Fix White Balance"),
            ("fix_exposure",                "Fix Exposure"),
            ("reduce_chromatic_aberration", "Fix Chromatic Aberration"),
        ],
        "ai_corrections": [
            ("fix_face",                 "Fix Face Distortion"),
            ("fix_eyes",                 "Fix Eyes"),
            ("fix_hands",                "Fix Hands & Fingers"),
            ("fix_teeth_mouth",          "Fix Teeth & Mouth"),
            ("fix_body_anatomy",         "Fix Body Anatomy"),
            ("fix_skin_texture",         "Fix Skin Texture"),
            ("fix_hair",                 "Fix Hair"),
            ("fix_background_coherence", "Fix Background Coherence"),
        ],
        "compositing": [
            ("harmonize_lighting",  "Harmonize Lighting"),
            ("match_shadows",       "Match Shadows"),
            ("blend_edges",         "Blend Edges"),
            ("color_harmonize",     "Color Harmonize"),
            ("fix_reflections",     "Fix Reflections"),
            ("integrate_elements",  "Integrate Elements"),
            ("match_ambient",       "Match Ambient Light"),
            ("depth_consistency",   "Depth Consistency"),
        ],
        "object_edits": [
            ("delete_object",        "Delete Object"),
            ("replace_object",       "Replace Object"),
            ("change_object_color",  "Change Object Color"),
            ("change_object_material","Change Object Material"),
            ("add_vegetation",       "Add Vegetation"),
            ("add_people",           "Add People"),
            ("add_clouds",           "Add Clouds"),
            ("remove_people",        "Remove People"),
            ("add_water_reflection", "Add Water Reflection"),
            ("age_weathering",       "Add Aging / Weathering"),
            ("modernize",            "Modernize"),
            ("add_text_overlay",     "Add Text Overlay"),
        ],
    }

    hda_file = os.path.join(HDAS_DIR, "bria_fibo_edit_recipes.hda")
    _remove_existing(hda_file, base_name="bria_fibo_edit_recipes")
    # Clean up old-name HDA from before rename
    _remove_existing(os.path.join(HDAS_DIR, "bria_fibo_edit_presets.hda"), base_name="bria_fibo_edit_presets")

    hda_node, cop_net = _build_cop_hda("bria_fibo_edit_recipes", "Bria FIBO Edit Recipes", "2.0.0", hda_file, num_inputs=1)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # --- Main tab ---
    main = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    # Category menu (top-tier)
    cat_tokens = [tok for tok, _lbl in _CATEGORIES]
    cat_labels = [lbl for _tok, lbl in _CATEGORIES]
    cat_menu = hou.MenuParmTemplate(
        "category", "Category",
        menu_items=cat_tokens,
        menu_labels=cat_labels,
        default_value=0,
        script_callback="hou.phm().on_category_changed(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(cat_menu)

    # Per-category preset menus (second-tier, each hidden unless its category is active)
    for cat_tok, _cat_label in _CATEGORIES:
        if cat_tok == "custom":
            continue  # No preset submenu for Custom
        presets = _PRESET_MENUS.get(cat_tok, [])
        if not presets:
            continue
        p_tokens = [p[0] for p in presets]
        p_labels = [p[1] for p in presets]
        preset_menu = hou.MenuParmTemplate(
            f"preset_{cat_tok}", "Preset",
            menu_items=p_tokens,
            menu_labels=p_labels,
            default_value=0,
            script_callback="hou.phm().on_preset_changed(kwargs)",
            script_callback_language=hou.scriptLanguage.Python,
        )
        preset_menu.setConditional(hou.parmCondType.HideWhen, '{ category != "' + cat_tok + '" }')
        main.addParmTemplate(preset_menu)

    # --- Object Targeting (visible only for targeted object_edits presets) ---
    _HIDE_NOT_OBJ_EDITS = '{ category != "object_edits" }'

    obj_name = hou.StringParmTemplate(
        "obj_target_name_#", "Object", 1, default_value=[""],
        script_callback="hou.phm().on_object_target_changed(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    obj_name.setHelp("Name of the object to target (e.g. 'red car', 'wooden fence')")

    obj_mod = hou.StringParmTemplate(
        "obj_target_mod_#", "With / To", 1, default_value=[""],
        script_callback="hou.phm().on_object_target_changed(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    obj_mod.setHelp("For Replace: replacement description. For Color: target color. For Material: target material. Leave empty for Delete.")

    obj_targets = hou.FolderParmTemplate(
        "obj_target_count", "Object Targets",
        folder_type=hou.folderType.MultiparmBlock,
    )
    obj_targets.addParmTemplate(obj_name)
    obj_targets.addParmTemplate(obj_mod)
    obj_targets.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_OBJ_EDITS)
    main.addParmTemplate(obj_targets)

    # --- Compositing Element Targeting (visible only for compositing category) ---
    _HIDE_NOT_COMPOSITING = '{ category != "compositing" }'

    comp_desc = hou.StringParmTemplate(
        "comp_element_desc_#", "Element", 1, default_value=[""],
        script_callback="hou.phm().on_comp_element_changed(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    comp_desc.setHelp("Describe a composited element (e.g. 'the car in the foreground', 'the person near the bench')")

    comp_elements = hou.FolderParmTemplate(
        "comp_element_count", "Composited Elements",
        folder_type=hou.folderType.MultiparmBlock,
    )
    comp_elements.addParmTemplate(comp_desc)
    comp_elements.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_COMPOSITING)
    main.addParmTemplate(comp_elements)

    # Hidden tracking parm for auto-prompt edit detection
    auto_prompt = hou.StringParmTemplate("_auto_prompt", "", 1, default_value=[""])
    auto_prompt.hide(True)
    main.addParmTemplate(auto_prompt)

    # Prompt (always visible — auto-populated from preset, user can edit)
    prompt_parm = hou.StringParmTemplate("prompt", "Prompt", 1, default_value=[""])
    prompt_parm.setTags({"editor": "1", "editorLines": "3"})
    main.addParmTemplate(prompt_parm)

    main.addParmTemplate(hou.StringParmTemplate("negative_prompt", "Negative Prompt", 1, default_value=[""]))

    main.addParmTemplate(hou.SeparatorParmTemplate("sep1"))

    btn = hou.ButtonParmTemplate(
        "edit", "Run FIBO Edit Presets",
        script_callback="hou.phm().on_fibo_edit_recipes(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(btn)

    ptg.append(main)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.IntParmTemplate("guidance_scale", "Guidance Scale", 1, default_value=(5,), min=1, max=5))
    settings.addParmTemplate(hou.IntParmTemplate("seed", "Seed", 1, default_value=(0,), min=0, max=999999))
    settings.addParmTemplate(hou.IntParmTemplate("steps_num", "Steps", 1, default_value=(0,), min=0, max=50))

    ptg.append(settings)

    # --- VGL Editor tab (shared helper) ---
    ptg.append(_build_vgl_editor_tab(
        generate_callback="hou.phm().on_fibo_edit_recipes(kwargs)",
        generate_label="Run FIBO Edit Presets",
    ))

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria FIBO Edit Recipes v2.0.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Edit images with categorized preset prompts using Bria AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP2_color")
    except:
        pass

    # OnInputChanged: populate structured prompt + VGL fields from upstream
    on_input_changed = textwrap.dedent("""\
        import json as _json

        node = kwargs["node"]
        input_index = kwargs["input_index"]

        if input_index == 0:
            found = False
            inputs = node.inputs()
            input_op = inputs[0] if len(inputs) > 0 else None

            if input_op is not None:
                result_parm = input_op.parm("result_json")
                if result_parm:
                    json_val = result_parm.eval()
                    if json_val and json_val.strip():
                        # Re-format with indentation for readability
                        try:
                            json_val = _json.dumps(_json.loads(json_val), indent=2)
                        except Exception:
                            pass
                        node.parm("structured_prompt").set(json_val)
                        found = True
                        # Parse into structured VGL fields
                        try:
                            phm = node.hdaModule()
                            if hasattr(phm, "on_parse_vgl"):
                                phm.on_parse_vgl({"node": node})
                        except Exception:
                            pass

            if not found:
                node.parm("structured_prompt").set("")
                # Clear all VGL structured parms
                try:
                    phm = node.hdaModule()
                    if hasattr(phm, "clear_vgl_parms"):
                        phm.clear_vgl_parms(node)
                except Exception:
                    pass
    """)
    hda_def.addSection("OnInputChanged", on_input_changed)
    hda_def.setExtraFileOption("OnInputChanged/IsPython", True)

    pymod = _load_pymodule("bria_fibo_edit_recipes.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_fibo_edit_recipes")


# ===================================================================
# 3. BRIA GENERATE STRUCTURED PROMPT
# ===================================================================

def build_generate_structured_prompt():
    print("\n--- Building Bria Generate VGL ---")

    hda_file = os.path.join(HDAS_DIR, "bria_generate_vgl.hda")
    _remove_existing(hda_file)
    # Remove old name if present
    _remove_existing(os.path.join(HDAS_DIR, "bria_generate_structured_prompt.hda"))

    # Optional image input — text, image, or both → JSON out
    hda_node, cop_net = _build_cop_hda("bria_generate_vgl", "Bria Generate VGL", "1.0.0", hda_file, min_inputs=0, max_inputs=1)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # --- Main tab ---
    main = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    main.addParmTemplate(hou.StringParmTemplate("prompt", "Text Prompt", 1, default_value=[""]))
    main.addParmTemplate(hou.IntParmTemplate("seed", "Seed", 1, default_value=(0,), min=0, max=999999))
    main.addParmTemplate(hou.ToggleParmTemplate("lock_vgl", "Lock VGL", default_value=False))

    main.addParmTemplate(hou.SeparatorParmTemplate("sep1"))

    btn = hou.ButtonParmTemplate(
        "generate", "Generate VGL (Structured Prompt)",
        script_callback="hou.phm().on_generate_structured_prompt(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(btn)

    main.addParmTemplate(hou.SeparatorParmTemplate("sep2"))

    # Short description label (populated after generation)
    desc_parm = hou.LabelParmTemplate("vgl_description", "Description:",
                                       column_labels=["(generate to see description)"])
    main.addParmTemplate(desc_parm)

    # Result JSON output — multi-line editor, editable for manual tweaks
    result = hou.StringParmTemplate("result_json", "Result JSON", 1, default_value=[""])
    result.setTags({"editor": "1", "editorLines": "15"})
    main.addParmTemplate(result)

    # Send to FIBO Generate button
    send_btn = hou.ButtonParmTemplate(
        "send_downstream", "Send to FIBO Generate",
        script_callback="hou.phm().on_send_downstream(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(send_btn)

    ptg.append(main)

    # --- Results (hidden, for node chaining — passthrough image path) ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("MISC_python")
    except:
        pass

    pymod = _load_pymodule("bria_generate_vgl.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_generate_vgl", max_inputs=1)


# ===================================================================
# 4. BRIA FIBO GENERATE (was "Generate Image")
# ===================================================================

def build_generate_image():
    print("\n--- Building Bria FIBO Generate ---")

    hda_file = os.path.join(HDAS_DIR, "bria_fibo_generate.hda")
    # Clean up all old definitions (Carlos's original + our old name)
    _remove_existing(hda_file, base_name="bria_fibo_generate")
    _remove_existing(os.path.join(HDAS_DIR, "bria_generate_image.hda"), base_name="bria_generate_image")

    # Optional input: accepts structured prompt from upstream node (min=0, max=1)
    hda_node, cop_net = _build_cop_hda("bria_fibo_generate", "Bria FIBO Generate", "1.0", hda_file, min_inputs=0, max_inputs=1)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    _DISABLE_BASIC = "{ use_basic_prompt == 0 }"
    _DISABLE_STRUCT = "{ use_structured_prompt == 0 }"

    _TOGGLE_BASIC_CB = (
        "n=kwargs['node']\n"
        "if n.parm('use_basic_prompt').eval():\n"
        " n.parm('use_structured_prompt').set(0)"
    )
    _TOGGLE_STRUCT_CB = (
        "n=kwargs['node']\n"
        "if n.parm('use_structured_prompt').eval():\n"
        " n.parm('use_basic_prompt').set(0)"
    )

    # --- Basic Prompt tab ---
    basic = hou.FolderParmTemplate("main", "Basic Prompt", folder_type=hou.folderType.Tabs)

    basic_toggle = hou.ToggleParmTemplate("use_basic_prompt", "Use Basic Prompt", default_value=True)
    basic_toggle.setScriptCallback(_TOGGLE_BASIC_CB)
    basic_toggle.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    basic.addParmTemplate(basic_toggle)

    basic.addParmTemplate(hou.SeparatorParmTemplate("basic_sep0"))

    # Prompt (multi-line) — greyed out when basic mode is off
    prompt_parm = hou.StringParmTemplate("prompt", "Prompt", 1, default_value=[""])
    prompt_parm.setTags({"editor": "1", "editorLines": "8"})
    prompt_parm.setConditional(hou.parmCondType.DisableWhen, _DISABLE_BASIC)
    basic.addParmTemplate(prompt_parm)

    # Negative Prompt — toggle to reveal, greyed out when basic mode is off
    neg_toggle = hou.ToggleParmTemplate("use_negative_prompt", "Negative Prompt", default_value=False)
    neg_toggle.setConditional(hou.parmCondType.DisableWhen, _DISABLE_BASIC)
    basic.addParmTemplate(neg_toggle)
    neg_parm = hou.StringParmTemplate("negative_prompt", "", 1, default_value=[""])
    neg_parm.setConditional(hou.parmCondType.HideWhen, "{ use_negative_prompt == 0 }")
    basic.addParmTemplate(neg_parm)

    basic.addParmTemplate(hou.SeparatorParmTemplate("sep1"))

    btn = hou.ButtonParmTemplate(
        "generate", "Run FIBO Generate",
        script_callback="hou.phm().on_generate_image(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    basic.addParmTemplate(btn)

    ptg.append(basic)

    # --- Structured Prompt tab (was VGL Editor) ---
    struct_tab = _build_vgl_editor_tab(
        generate_callback="hou.phm().on_generate_image(kwargs)",
        generate_label="Run FIBO Generate",
        tab_label="Structured Prompt",
        disable_condition=_DISABLE_STRUCT,
    )
    # Insert mode toggle at position 0 (before all VGL content)
    struct_toggle = hou.ToggleParmTemplate("use_structured_prompt", "Use Structured Prompt", default_value=False)
    struct_toggle.setScriptCallback(_TOGGLE_STRUCT_CB)
    struct_toggle.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    struct_tab.addParmTemplate(struct_toggle)  # will reorder below
    # Move toggle to the top by rebuilding the folder
    templates = list(struct_tab.parmTemplates())
    # Pop the last item (toggle) and insert at front
    toggle_tmpl = templates.pop()
    templates.insert(0, toggle_tmpl)
    templates.insert(1, hou.SeparatorParmTemplate("struct_sep0"))
    struct_tab.setParmTemplates(templates)
    ptg.append(struct_tab)

    # --- Settings tab (extracted from old Main) ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.ToggleParmTemplate("preserve_alpha", "Preserve Alpha", default_value=True))

    ar_items = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"]
    settings.addParmTemplate(hou.MenuParmTemplate(
        "aspect_ratio", "Aspect Ratio",
        menu_items=ar_items, menu_labels=ar_items, default_value=0,
    ))

    settings.addParmTemplate(hou.MenuParmTemplate(
        "pipeline", "Model",
        menu_items=["standard", "tailored"],
        menu_labels=["standard", "tailored"],
        default_value=0,
    ))

    settings.addParmTemplate(hou.IntParmTemplate("seed", "Seed", 1, default_value=(0,), min=0, max=999999))
    settings.addParmTemplate(hou.IntParmTemplate("guidance_scale", "Guidance Scale", 1, default_value=(4,), min=1, max=5))
    settings.addParmTemplate(hou.IntParmTemplate("steps_num", "Steps", 1, default_value=(0,), min=0, max=50))

    ptg.append(settings)

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria FIBO Generate v1.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Generate images using Bria FIBO AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    # Hidden parms
    sync_parm = hou.ToggleParmTemplate("sync", "Sync", default_value=True)
    sync_parm.hide(True)
    ptg.append(sync_parm)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP2_fetch")
    except:
        pass

    # OnInputChanged: populate structured prompt + VGL fields from upstream,
    # and auto-switch between Basic Prompt / Structured Prompt mode.
    on_input_changed = textwrap.dedent("""\
        import json as _json

        node = kwargs["node"]
        input_index = kwargs["input_index"]

        if input_index == 0:
            found = False
            inputs = node.inputs()
            input_op = inputs[0] if len(inputs) > 0 else None

            if input_op is not None:
                result_parm = input_op.parm("result_json")
                if result_parm:
                    json_val = result_parm.eval()
                    if json_val and json_val.strip():
                        # Re-format with indentation for readability
                        try:
                            json_val = _json.dumps(_json.loads(json_val), indent=2)
                        except Exception:
                            pass
                        node.parm("structured_prompt").set(json_val)
                        found = True
                        # Auto-switch to Structured Prompt mode
                        sp = node.parm("use_structured_prompt")
                        bp = node.parm("use_basic_prompt")
                        if sp is not None:
                            sp.set(1)
                        if bp is not None:
                            bp.set(0)
                        # Parse into structured VGL fields
                        try:
                            phm = node.hdaModule()
                            if hasattr(phm, "on_parse_vgl"):
                                phm.on_parse_vgl({"node": node})
                        except Exception:
                            pass

            if not found:
                node.parm("structured_prompt").set("")
                # Auto-switch back to Basic Prompt mode
                sp = node.parm("use_structured_prompt")
                bp = node.parm("use_basic_prompt")
                if sp is not None:
                    sp.set(0)
                if bp is not None:
                    bp.set(1)
                # Clear all VGL structured parms
                try:
                    phm = node.hdaModule()
                    if hasattr(phm, "clear_vgl_parms"):
                        phm.clear_vgl_parms(node)
                except Exception:
                    pass
    """)
    hda_def.addSection("OnInputChanged", on_input_changed)
    hda_def.setExtraFileOption("OnInputChanged/IsPython", True)

    pymod = _load_pymodule("bria_generate_image.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_fibo_generate", max_inputs=1)


# ===================================================================
# 5. BRIA FIBO EDIT (rebuilt v2 — replaces Carlos's original)
# ===================================================================

def build_fibo_edit():
    print("\n--- Building Bria FIBO Edit ---")

    hda_file = os.path.join(HDAS_DIR, "bria_fibo_edit_v2.hda")
    _remove_existing(hda_file)

    hda_node, cop_net = _build_cop_hda("bria_fibo_edit", "Bria FIBO Edit", "2.0", hda_file, num_inputs=1)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    _DISABLE_BASIC = "{ use_basic_prompt == 0 }"
    _DISABLE_STRUCT = "{ use_structured_prompt == 0 }"

    _TOGGLE_BASIC_CB = (
        "n=kwargs['node']\n"
        "if n.parm('use_basic_prompt').eval():\n"
        " n.parm('use_structured_prompt').set(0)"
    )
    _TOGGLE_STRUCT_CB = (
        "n=kwargs['node']\n"
        "if n.parm('use_structured_prompt').eval():\n"
        " n.parm('use_basic_prompt').set(0)"
    )

    # --- Basic Prompt tab ---
    basic = hou.FolderParmTemplate("main", "Basic Prompt", folder_type=hou.folderType.Tabs)

    basic_toggle = hou.ToggleParmTemplate("use_basic_prompt", "Use Basic Prompt", default_value=True)
    basic_toggle.setScriptCallback(_TOGGLE_BASIC_CB)
    basic_toggle.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    basic.addParmTemplate(basic_toggle)

    basic.addParmTemplate(hou.SeparatorParmTemplate("basic_sep0"))

    # Prompt (multi-line) — greyed out when basic mode is off
    prompt_parm = hou.StringParmTemplate("prompt", "Prompt", 1, default_value=[""])
    prompt_parm.setTags({"editor": "1", "editorLines": "4"})
    prompt_parm.setConditional(hou.parmCondType.DisableWhen, _DISABLE_BASIC)
    basic.addParmTemplate(prompt_parm)

    # Negative Prompt — toggle to reveal, greyed out when basic mode is off
    neg_toggle = hou.ToggleParmTemplate("use_negative_prompt", "Negative Prompt", default_value=False)
    neg_toggle.setConditional(hou.parmCondType.DisableWhen, _DISABLE_BASIC)
    basic.addParmTemplate(neg_toggle)
    neg_parm = hou.StringParmTemplate("negative_prompt", "", 1, default_value=[""])
    neg_parm.setConditional(hou.parmCondType.HideWhen, "{ use_negative_prompt == 0 }")
    basic.addParmTemplate(neg_parm)

    basic.addParmTemplate(hou.SeparatorParmTemplate("sep1"))

    btn = hou.ButtonParmTemplate(
        "edit", "Run FIBO Edit",
        script_callback="hou.phm().on_fibo_edit(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    basic.addParmTemplate(btn)

    ptg.append(basic)

    # --- Structured Prompt tab (was VGL Editor) ---
    struct_tab = _build_vgl_editor_tab(
        generate_callback="hou.phm().on_fibo_edit(kwargs)",
        generate_label="Run FIBO Edit",
        tab_label="Structured Prompt",
        disable_condition=_DISABLE_STRUCT,
    )
    # Insert mode toggle at position 0 (before all VGL content)
    struct_toggle = hou.ToggleParmTemplate("use_structured_prompt", "Use Structured Prompt", default_value=False)
    struct_toggle.setScriptCallback(_TOGGLE_STRUCT_CB)
    struct_toggle.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    struct_tab.addParmTemplate(struct_toggle)  # will reorder below
    # Move toggle to the top by rebuilding the folder
    templates = list(struct_tab.parmTemplates())
    toggle_tmpl = templates.pop()
    templates.insert(0, toggle_tmpl)
    templates.insert(1, hou.SeparatorParmTemplate("struct_sep0"))
    struct_tab.setParmTemplates(templates)
    ptg.append(struct_tab)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.IntParmTemplate("guidance_scale", "Guidance Scale", 1, default_value=(5,), min=1, max=5))
    settings.addParmTemplate(hou.IntParmTemplate("seed", "Seed", 1, default_value=(0,), min=0, max=999999))
    settings.addParmTemplate(hou.IntParmTemplate("steps_num", "Steps", 1, default_value=(0,), min=0, max=50))

    ptg.append(settings)

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria FIBO Edit v2.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Edit images using Bria FIBO AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP2_color")
    except:
        pass

    # OnInputChanged: populate structured prompt + VGL fields from upstream,
    # and auto-switch between Basic Prompt / Structured Prompt mode.
    on_input_changed = textwrap.dedent("""\
        import json as _json

        node = kwargs["node"]
        input_index = kwargs["input_index"]

        if input_index == 0:
            found = False
            inputs = node.inputs()
            input_op = inputs[0] if len(inputs) > 0 else None

            if input_op is not None:
                result_parm = input_op.parm("result_json")
                if result_parm:
                    json_val = result_parm.eval()
                    if json_val and json_val.strip():
                        # Re-format with indentation for readability
                        try:
                            json_val = _json.dumps(_json.loads(json_val), indent=2)
                        except Exception:
                            pass
                        node.parm("structured_prompt").set(json_val)
                        found = True
                        # Auto-switch to Structured Prompt mode
                        sp = node.parm("use_structured_prompt")
                        bp = node.parm("use_basic_prompt")
                        if sp is not None:
                            sp.set(1)
                        if bp is not None:
                            bp.set(0)
                        # Parse into structured VGL fields
                        try:
                            phm = node.hdaModule()
                            if hasattr(phm, "on_parse_vgl"):
                                phm.on_parse_vgl({"node": node})
                        except Exception:
                            pass

            if not found:
                node.parm("structured_prompt").set("")
                # Auto-switch back to Basic Prompt mode
                sp = node.parm("use_structured_prompt")
                bp = node.parm("use_basic_prompt")
                if sp is not None:
                    sp.set(0)
                if bp is not None:
                    bp.set(1)
                # Clear all VGL structured parms
                try:
                    phm = node.hdaModule()
                    if hasattr(phm, "clear_vgl_parms"):
                        phm.clear_vgl_parms(node)
                except Exception:
                    pass
    """)
    hda_def.addSection("OnInputChanged", on_input_changed)
    hda_def.setExtraFileOption("OnInputChanged/IsPython", True)

    pymod = _load_pymodule("bria_fibo_edit.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_fibo_edit")


# ===================================================================
# 6. BRIA EXPAND
# ===================================================================

def build_expand():
    print("\n--- Building Bria Expand ---")

    hda_file = os.path.join(HDAS_DIR, "bria_expand_v2.hda")
    _remove_existing(hda_file, base_name="bria_expand_v2")

    hda_node, cop_net = _build_cop_hda("bria_expand_v2", "Bria Expand", "2.0", hda_file, num_inputs=1)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # HideWhen conditions for expansion mode fields
    _HIDE_NOT_ASPECT = '{ expansion_mode != "aspect_ratio" }'
    _HIDE_NOT_DIRECTIONAL = '{ expansion_mode != "directional" }'
    _HIDE_NOT_CANVAS = '{ expansion_mode != "canvas_size" }'

    # --- Main tab ---
    main = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    # Expansion Mode selector
    main.addParmTemplate(hou.MenuParmTemplate(
        "expansion_mode", "Expansion Mode",
        menu_items=["aspect_ratio", "directional", "canvas_size"],
        menu_labels=["Aspect Ratio", "Directional (per-side)", "Canvas Size"],
        default_value=1,  # Default to Directional
    ))

    main.addParmTemplate(hou.SeparatorParmTemplate("mode_sep"))

    # -- Aspect Ratio mode fields --
    ar = hou.MenuParmTemplate(
        "aspect_ratio", "Aspect Ratio",
        menu_items=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"],
        menu_labels=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"],
        default_value=0,
    )
    ar.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_ASPECT)
    main.addParmTemplate(ar)

    # -- Directional mode fields --
    for name, label, default in [
        ("expand_left", "Expand Left (px)", 0),
        ("expand_right", "Expand Right (px)", 0),
        ("expand_top", "Expand Top (px)", 0),
        ("expand_bottom", "Expand Bottom (px)", 0),
    ]:
        p = hou.IntParmTemplate(name, label, 1, default_value=[default], min=0, max=2000,
                                min_is_strict=True, max_is_strict=False)
        p.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_DIRECTIONAL)
        main.addParmTemplate(p)

    # -- Canvas Size mode fields --
    cw = hou.IntParmTemplate("canvas_width", "Canvas Width", 1, default_value=[1024], min=1, max=5000,
                             min_is_strict=True, max_is_strict=False)
    cw.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_CANVAS)
    main.addParmTemplate(cw)

    ch = hou.IntParmTemplate("canvas_height", "Canvas Height", 1, default_value=[1024], min=1, max=5000,
                             min_is_strict=True, max_is_strict=False)
    ch.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_CANVAS)
    main.addParmTemplate(ch)

    anchor = hou.MenuParmTemplate(
        "anchor", "Anchor",
        menu_items=["top-left", "center"],
        menu_labels=["Top-Left", "Center"],
        default_value=0,
    )
    anchor.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_CANVAS)
    main.addParmTemplate(anchor)

    main.addParmTemplate(hou.SeparatorParmTemplate("prompt_sep"))

    # -- Prompt --
    prompt_parm = hou.StringParmTemplate("prompt", "Prompt", 1, default_value=[""])
    prompt_parm.setTags({"editor": "1", "editorLines": "4"})
    main.addParmTemplate(prompt_parm)

    # -- Negative Prompt (toggle + field) --
    main.addParmTemplate(hou.ToggleParmTemplate("enable_negative_prompt", "Negative Prompt", default_value=False))
    neg_parm = hou.StringParmTemplate("negative_prompt", "", 1, default_value=[""])
    neg_parm.setTags({"editor": "1", "editorLines": "2"})
    neg_parm.setConditional(hou.parmCondType.HideWhen, "{ enable_negative_prompt == 0 }")
    main.addParmTemplate(neg_parm)

    main.addParmTemplate(hou.SeparatorParmTemplate("btn_sep"))

    # -- Expand button --
    btn = hou.ButtonParmTemplate(
        "expand", "Run Expand",
        script_callback="hou.phm().on_expand(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(btn)

    ptg.append(main)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.ToggleParmTemplate("preserve_alpha", "Preserve Alpha", default_value=True))
    settings.addParmTemplate(hou.IntParmTemplate("seed", "Seed (0 = random)", 1, default_value=[0],
                                                  min=0, max=2147483647,
                                                  min_is_strict=True, max_is_strict=True))
    settings.addParmTemplate(hou.ToggleParmTemplate("fast", "Fast Mode", default_value=False))
    settings.addParmTemplate(hou.SeparatorParmTemplate("mod_sep"))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_input", "Content Moderation (Input)", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_output", "Content Moderation (Output)", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_prompt", "Content Moderation (Prompt)", default_value=True))
    ptg.append(settings)

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria Expand v2.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Expand (outpaint) image canvas using Bria AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP2_expand")
    except:
        pass

    pymod = _load_pymodule("bria_expand.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_expand_v2")


def build_rmbg():
    print("\n--- Building Bria RMBG ---")

    hda_file = os.path.join(HDAS_DIR, "bria_rmbg_v2.hda")
    _remove_existing(hda_file, base_name="bria_rmbg_v2")

    hda_node, cop_net = _build_cop_hda("bria_rmbg_v2", "Bria RMBG", "2.0", hda_file, num_inputs=1)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # --- Main tab ---
    main = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    # Remove Background button
    btn = hou.ButtonParmTemplate(
        "rmbg", "Remove Background",
        script_callback="hou.phm().on_rmbg(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(btn)

    ptg.append(main)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.ToggleParmTemplate("preserve_alpha", "Preserve Alpha", default_value=True))
    settings.addParmTemplate(hou.ToggleParmTemplate("keep_original_size", "Keep Original Size", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("force_bg_detection", "Force Background Detection", default_value=False))
    settings.addParmTemplate(hou.SeparatorParmTemplate("mod_sep"))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_input", "Content Moderation (Input)", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_output", "Content Moderation (Output)", default_value=False))
    ptg.append(settings)

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria RMBG v2.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Remove image background using Bria AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP2_chromakey")
    except:
        pass

    pymod = _load_pymodule("bria_rmbg.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_rmbg_v2")


def build_erase():
    print("\n--- Building Bria Erase ---")

    hda_file = os.path.join(HDAS_DIR, "bria_erase_v2.hda")
    _remove_existing(hda_file, base_name="bria_erase_v2")

    hda_node, cop_net = _build_cop_hda("bria_erase_v2", "Bria Erase", "2.0", hda_file, num_inputs=2)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # --- Main tab ---
    main = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    main.addParmTemplate(hou.LabelParmTemplate(
        "input_help", "Inputs:", column_labels=["Input 1 = Image, Input 2 = Mask"]))

    main.addParmTemplate(hou.SeparatorParmTemplate("btn_sep"))

    btn = hou.ButtonParmTemplate(
        "erase", "Run Erase",
        script_callback="hou.phm().on_erase(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(btn)

    ptg.append(main)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.ToggleParmTemplate("preserve_alpha", "Preserve Alpha", default_value=True))
    settings.addParmTemplate(hou.IntParmTemplate("seed", "Seed (0 = random)", 1, default_value=[0],
                                                  min=0, max=2147483647,
                                                  min_is_strict=True, max_is_strict=True))
    settings.addParmTemplate(hou.SeparatorParmTemplate("mod_sep"))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_input", "Content Moderation (Input)", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_output", "Content Moderation (Output)", default_value=False))
    ptg.append(settings)

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria Erase v2.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Erase objects from images using Bria AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP_sdfadjust")
    except:
        pass

    pymod = _load_pymodule("bria_erase.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_erase_v2", max_inputs=2)


def build_upscale():
    print("\n--- Building Bria Upscale ---")

    hda_file = os.path.join(HDAS_DIR, "bria_upscale_v2.hda")
    _remove_existing(hda_file, base_name="bria_upscale_v2")

    hda_node, cop_net = _build_cop_hda("bria_upscale_v2", "Bria Upscale", "2.0", hda_file, num_inputs=1)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # --- Main tab ---
    main = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    main.addParmTemplate(hou.MenuParmTemplate(
        "desired_resolution", "Resolution",
        menu_items=["2x", "4x"],
        menu_labels=["2x", "4x"],
        default_value=0,
    ))

    main.addParmTemplate(hou.SeparatorParmTemplate("btn_sep"))

    btn = hou.ButtonParmTemplate(
        "upscale", "Run Upscale",
        script_callback="hou.phm().on_upscale(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(btn)

    ptg.append(main)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.ToggleParmTemplate("preserve_alpha", "Preserve Alpha", default_value=True))
    settings.addParmTemplate(hou.IntParmTemplate("seed", "Seed (0 = random)", 1, default_value=[0],
                                                  min=0, max=2147483647,
                                                  min_is_strict=True, max_is_strict=True))
    settings.addParmTemplate(hou.SeparatorParmTemplate("mod_sep"))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_input", "Content Moderation (Input)", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_output", "Content Moderation (Output)", default_value=False))
    ptg.append(settings)

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria Upscale v2.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Increase image resolution using Bria AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP2_scale")
    except:
        pass

    pymod = _load_pymodule("bria_upscale.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_upscale_v2")


def build_genfill():
    print("\n--- Building Bria GenFill ---")

    hda_file = os.path.join(HDAS_DIR, "bria_genfill_v2.hda")
    _remove_existing(hda_file, base_name="bria_genfill_v2")

    hda_node, cop_net = _build_cop_hda("bria_genfill_v2", "Bria GenFill", "2.0", hda_file, num_inputs=2)
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # --- Main tab ---
    main = hou.FolderParmTemplate("main", "Main", folder_type=hou.folderType.Tabs)

    # Prompt
    prompt_parm = hou.StringParmTemplate("prompt", "Prompt", 1, default_value=[""])
    prompt_parm.setTags({"editor": "1", "editorLines": "4"})
    main.addParmTemplate(prompt_parm)

    # Negative Prompt (toggle + field)
    main.addParmTemplate(hou.ToggleParmTemplate("enable_negative_prompt", "Negative Prompt", default_value=False))
    neg_parm = hou.StringParmTemplate("negative_prompt", "", 1, default_value=[""])
    neg_parm.setTags({"editor": "1", "editorLines": "2"})
    neg_parm.setConditional(hou.parmCondType.HideWhen, "{ enable_negative_prompt == 0 }")
    main.addParmTemplate(neg_parm)

    main.addParmTemplate(hou.SeparatorParmTemplate("btn_sep"))

    btn = hou.ButtonParmTemplate(
        "genfill", "Run GenFill",
        script_callback="hou.phm().on_genfill(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    main.addParmTemplate(btn)

    ptg.append(main)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)
    settings.addParmTemplate(hou.ToggleParmTemplate("preserve_alpha", "Preserve Alpha", default_value=True))
    settings.addParmTemplate(hou.IntParmTemplate("seed", "Seed (0 = random)", 1, default_value=[0],
                                                  min=0, max=2147483647,
                                                  min_is_strict=True, max_is_strict=True))
    settings.addParmTemplate(hou.ToggleParmTemplate("refine_prompt", "Refine Prompt", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("fast", "Fast Mode", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("keep_original_size", "Keep Original Size", default_value=False))
    settings.addParmTemplate(hou.StringParmTemplate("tailored_model_id", "Tailored Model ID", 1, default_value=[""]))
    settings.addParmTemplate(hou.SeparatorParmTemplate("mod_sep"))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_input", "Content Moderation (Input)", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_output", "Content Moderation (Output)", default_value=False))
    settings.addParmTemplate(hou.ToggleParmTemplate("content_moderation_prompt", "Content Moderation (Prompt)", default_value=True))
    ptg.append(settings)

    # --- Results tab ---
    results = hou.FolderParmTemplate("results", "Results", folder_type=hou.folderType.Tabs)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.setConditional(hou.parmCondType.DisableWhen, "{ result_path != __never_match__ }")
    results.addParmTemplate(rp)
    ptg.append(results)

    # --- History tab ---
    ptg.append(_build_history_tab())

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria GenFill v2.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_about", "About this HDA:", column_labels=["Generative fill masked regions using Bria AI"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_conn", "Connection:", column_labels=[""]))
    ptg.append(info)

    # --- Advanced tab ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("COP_monotosdf")
    except:
        pass

    pymod = _load_pymodule("bria_genfill.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_genfill_v2", max_inputs=2)


# ===================================================================
# 11. BRIA VIEWPORT RENDER v2
# ===================================================================

def build_viewport_render():
    """Build Viewport Render as an OBJ-level HDA (captures 3D viewport, not COP input)."""
    print("\n--- Building Bria Viewport Render v2 ---")

    hda_file = os.path.join(HDAS_DIR, "bria_viewport_render_v2.hda")
    _remove_existing(hda_file, base_name="bria_viewport_render")
    # Also clean up old restyle HDA
    old_restyle = os.path.join(HDAS_DIR, "bria_viewport_restyle_v2.hda")
    _remove_existing(old_restyle, base_name="bria_viewport_restyle")

    # --- Create OBJ-level HDA (not COP — this node operates on the 3D viewport) ---
    obj = hou.node("/obj")
    temp = obj.node("_bria_vr_builder_temp")
    if temp:
        temp.destroy()
    temp_geo = obj.createNode("geo", "_bria_vr_builder_temp")

    hda_node = temp_geo.createDigitalAsset(
        name="bria::bria_viewport_render::2.0",
        hda_file_name=hda_file,
        description="Bria Viewport Render",
        min_num_inputs=0,
        max_num_inputs=0,
        version="2.0",
    )
    hda_def = hda_node.type().definition()

    # --- Parameters ---
    ptg = hou.ParmTemplateGroup()

    # --- Preset menu data (mirrors CATEGORY_ORDER / PRESET_CATEGORIES in viewport_render.py) ---
    _VR_CATEGORIES = [
        ("custom",          "Custom"),
        ("vfx_simulations", "VFX Simulations"),
        ("environments",    "Environments"),
        ("lighting_mood",   "Lighting & Mood"),
        ("stylized",        "Stylized"),
    ]

    _VR_PRESET_MENUS = {
        "vfx_simulations": [
            ("destruction",   "Destruction & Debris"),
            ("water_ocean",   "Water & Ocean"),
            ("pyro_fire",     "Fire & Explosions"),
            ("smoke_clouds",  "Smoke & Clouds"),
            ("particles",     "Particles & Sparks"),
        ],
        "environments": [
            ("landscape_mountains", "Mountain Landscape"),
            ("landscape_forest",    "Forest & Vegetation"),
            ("landscape_desert",    "Desert & Arid"),
            ("landscape_coastal",   "Coastal & Beach"),
            ("building_exterior",   "Building Exterior"),
            ("building_interior",   "Building Interior"),
        ],
        "lighting_mood": [
            ("golden_hour",       "Golden Hour"),
            ("night_scene",       "Night Scene"),
            ("studio_lighting",   "Studio Lighting"),
            ("overcast_soft",     "Overcast & Soft"),
            ("dramatic_contrast", "Dramatic & High Contrast"),
            ("neon_urban",        "Neon & Urban Night"),
        ],
        "stylized": [
            ("motion_graphics",      "Motion Graphics"),
            ("abstract_procedural",  "Abstract Procedural Art"),
            ("concept_art",          "Concept Art"),
            ("architectural_viz",    "Architectural Visualization"),
            ("product_render",       "Product Render"),
        ],
    }

    # --- Toggle callbacks for Basic/Structured prompt mutual exclusion ---
    _TOGGLE_BASIC_CB = (
        "n=kwargs['node']\n"
        "if n.parm('use_basic_prompt').eval():\n"
        " n.parm('use_structured_prompt').set(0)"
    )
    _TOGGLE_STRUCT_CB = (
        "n=kwargs['node']\n"
        "if n.parm('use_structured_prompt').eval():\n"
        " n.parm('use_basic_prompt').set(0)"
    )

    _BASIC_DISABLE = '{ use_basic_prompt == 0 }'

    # --- Main tab ---
    main = hou.FolderParmTemplate("bria_render_folder", "Bria Viewport Render",
                                  folder_type=hou.folderType.Tabs)

    enable_parm = hou.ToggleParmTemplate("enable", "Enable", default_value=True)
    enable_parm.setHelp("Enable or disable this node")
    main.addParmTemplate(enable_parm)
    main.addParmTemplate(hou.SeparatorParmTemplate("sep1"))

    # --- Camera & Resolution (always visible at top) ---
    cam_mode = hou.MenuParmTemplate(
        "camera_mode", "Camera Mode",
        menu_items=["create_new", "use_existing"],
        menu_labels=["New Camera", "Existing Camera"],
        default_value=0,
    )
    cam_mode.setHelp("New Camera: creates a render camera at the current viewport angle. Existing Camera: use a camera already in your scene.")
    main.addParmTemplate(cam_mode)

    create_cam = hou.ButtonParmTemplate("create_camera", "Create Render Camera",
        script_callback="hou.phm().create_camera_callback()",
        script_callback_language=hou.scriptLanguage.Python)
    create_cam.setHelp("Create a camera at the current viewport position")
    create_cam.setConditional(hou.parmCondType.HideWhen, '{ camera_mode != "create_new" }')
    main.addParmTemplate(create_cam)

    cam_path = hou.StringParmTemplate(
        "camera_path", "Camera", 1,
        default_value=[""],
        string_type=hou.stringParmType.NodeReference,
    )
    cam_path.setHelp("Path to an existing camera node (e.g. /obj/cam1)")
    cam_path.setTags({"opfilter": "!!OBJ/CAMERA!!", "oprelative": "."})
    cam_path.setConditional(hou.parmCondType.HideWhen, '{ camera_mode != "use_existing" }')
    main.addParmTemplate(cam_path)

    validate_cam = hou.ButtonParmTemplate("validate_camera", "Validate Camera",
        script_callback="hou.phm().validate_existing_camera_callback()",
        script_callback_language=hou.scriptLanguage.Python)
    validate_cam.setHelp("Check if the camera exists and resolution is supported")
    validate_cam.setConditional(hou.parmCondType.HideWhen, '{ camera_mode != "use_existing" }')
    main.addParmTemplate(validate_cam)

    res_menu = hou.MenuParmTemplate(
        "resolution", "Resolution",
        menu_items=[
            "1024x1024", "1152x768", "768x1152",
            "1024x768", "768x1024",
            "960x768", "768x960",
            "1024x576", "576x1024",
        ],
        menu_labels=[
            "1024x1024 (1:1 Square)",
            "1152x768 (3:2 Landscape)", "768x1152 (2:3 Portrait)",
            "1024x768 (4:3 Landscape)", "768x1024 (3:4 Portrait)",
            "960x768 (5:4 Landscape)", "768x960 (4:5 Portrait)",
            "1024x576 (16:9 Wide)", "576x1024 (9:16 Tall)",
        ],
        default_value=0,
    )
    res_menu.setHelp("Output image resolution. When using an existing camera, this must match the camera's resolution.")
    main.addParmTemplate(res_menu)

    # --- Render controls (above prompt tabs so they're always visible) ---
    main.addParmTemplate(hou.SeparatorParmTemplate("sep_render"))

    render_mode = hou.MenuParmTemplate(
        "render_mode", "Iterations",
        menu_items=["create_new", "iterate"],
        menu_labels=["Create New Texture", "Iterate Texture"],
        default_value=0,
    )
    render_mode.setHelp(
        "Create New Texture: captures the original greybox geometry (ignoring applied textures).\n"
        "Iterate Texture: captures the viewport as-is, refining the current texture."
    )
    main.addParmTemplate(render_mode)

    main.addParmTemplate(hou.SeparatorParmTemplate("sep3"))

    render_btn = hou.ButtonParmTemplate("render_viewport", "Run Bria Render",
        script_callback="hou.phm().render_viewport_callback()",
        script_callback_language=hou.scriptLanguage.Python)
    render_btn.setHelp("Capture viewport and render with Bria AI")
    main.addParmTemplate(render_btn)

    # ===== Inner tab: Basic Prompt =====
    basic_tab = hou.FolderParmTemplate("basic_prompt_tab", "Basic Prompt",
                                        folder_type=hou.folderType.Tabs)

    use_basic = hou.ToggleParmTemplate("use_basic_prompt", "Use Basic Prompt", default_value=True)
    use_basic.setHelp("Use category-based preset prompts. Disable to use the Structured Prompt tab instead.")
    use_basic.setScriptCallback(_TOGGLE_BASIC_CB)
    use_basic.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    basic_tab.addParmTemplate(use_basic)

    # Category menu
    cat_tokens = [tok for tok, _lbl in _VR_CATEGORIES]
    cat_labels = [lbl for _tok, lbl in _VR_CATEGORIES]
    cat_menu = hou.MenuParmTemplate(
        "category", "Category",
        menu_items=cat_tokens,
        menu_labels=cat_labels,
        default_value=0,
        script_callback="hou.phm().on_category_changed(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    cat_menu.setHelp("Style category — select a category, then pick a preset below")
    cat_menu.setConditional(hou.parmCondType.DisableWhen, _BASIC_DISABLE)
    basic_tab.addParmTemplate(cat_menu)

    # Per-category preset menus (hidden unless category matches)
    for cat_tok, _cat_label in _VR_CATEGORIES:
        if cat_tok == "custom":
            continue
        presets = _VR_PRESET_MENUS.get(cat_tok, [])
        if not presets:
            continue
        p_tokens = [p[0] for p in presets]
        p_labels = [p[1] for p in presets]
        preset_menu = hou.MenuParmTemplate(
            f"preset_{cat_tok}", "Preset",
            menu_items=p_tokens,
            menu_labels=p_labels,
            default_value=0,
            script_callback="hou.phm().on_preset_changed(kwargs)",
            script_callback_language=hou.scriptLanguage.Python,
        )
        preset_menu.setHelp("Preset style within this category. Selecting a preset auto-fills the prompt.")
        preset_menu.setConditional(hou.parmCondType.HideWhen, '{ category != "' + cat_tok + '" }')
        preset_menu.setConditional(hou.parmCondType.DisableWhen, _BASIC_DISABLE)
        basic_tab.addParmTemplate(preset_menu)

    # Prompt (auto-populated from preset, user can edit)
    prompt = hou.StringParmTemplate(
        "prompt", "Prompt", 1,
        default_value=[""],
        string_type=hou.stringParmType.Regular,
    )
    prompt.setTags({"editor": "1", "editorLines": "8"})
    prompt.setHelp("Select a preset or write your own prompt describing the desired style")
    prompt.setConditional(hou.parmCondType.DisableWhen, _BASIC_DISABLE)
    basic_tab.addParmTemplate(prompt)

    neg_prompt = hou.StringParmTemplate(
        "negative_prompt", "Negative Prompt", 1,
        default_value=[""],
        string_type=hou.stringParmType.Regular,
    )
    neg_prompt.setHelp("Describe elements to avoid in the generated result")
    neg_prompt.setConditional(hou.parmCondType.DisableWhen, _BASIC_DISABLE)
    basic_tab.addParmTemplate(neg_prompt)

    main.addParmTemplate(basic_tab)

    # ===== Inner tab: Structured Prompt =====
    struct_tab = hou.FolderParmTemplate("struct_prompt_tab", "Structured Prompt",
                                         folder_type=hou.folderType.Tabs)

    use_struct = hou.ToggleParmTemplate("use_structured_prompt", "Use Structured Prompt",
                                         default_value=False)
    use_struct.setHelp("Use fine-grained VGL prompt fields for precise control. Disable to use Basic Prompt instead.")
    use_struct.setScriptCallback(_TOGGLE_STRUCT_CB)
    use_struct.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    struct_tab.addParmTemplate(use_struct)

    struct_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_genvgl"))

    # Generate VGL from text prompt
    gen_vgl_prompt = hou.StringParmTemplate(
        "generate_vgl_prompt", "Generate from", 1,
        default_value=[""],
        string_type=hou.stringParmType.Regular,
    )
    gen_vgl_prompt.setHelp("Describe your scene to auto-generate structured VGL fields")
    struct_tab.addParmTemplate(gen_vgl_prompt)

    gen_vgl_btn = hou.ButtonParmTemplate("generate_vgl", "Generate VGL from Prompt",
        script_callback="hou.phm().generate_vgl_callback()",
        script_callback_language=hou.scriptLanguage.Python)
    gen_vgl_btn.setHelp("Call Bria AI to generate a structured VGL prompt from your text description")
    struct_tab.addParmTemplate(gen_vgl_btn)

    struct_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_vgl"))

    # VGL editor fields (extracted from shared helper — no "Refresh from Upstream")
    vgl_editor = _build_vgl_editor_tab(
        generate_callback="hou.phm().render_viewport_callback()",
        generate_label="Run Bria Render",
        show_refresh_upstream=False,
        disable_condition='{ use_structured_prompt == 0 }',
    )
    for child in vgl_editor.parmTemplates():
        struct_tab.addParmTemplate(child)

    main.addParmTemplate(struct_tab)

    ptg.append(main)

    # --- Upscale tab ---
    upscale_tab = hou.FolderParmTemplate("upscale_tab", "Upscale",
                                          folder_type=hou.folderType.Tabs)

    upscale_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_upscale_top"))

    upscale_scale = hou.MenuParmTemplate(
        "upscale_scale", "Upscale",
        menu_items=["2x", "3x"],
        menu_labels=["2x", "3x"],
        default_value=0,
    )
    upscale_scale.setHelp("Multiply the result resolution (2x or 3x) using Bria Upscale")
    upscale_tab.addParmTemplate(upscale_scale)

    upscale_btn = hou.ButtonParmTemplate("upscale_result", "Run Bria Upscale",
        script_callback="hou.phm().upscale_result_callback()",
        script_callback_language=hou.scriptLanguage.Python)
    upscale_btn.setHelp("Upscale the rendered result using Bria AI")
    upscale_tab.addParmTemplate(upscale_btn)

    upscale_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_enhance"))

    enhance_res = hou.MenuParmTemplate(
        "enhance_resolution", "Enhance",
        menu_items=["1MP", "2MP", "4MP"],
        menu_labels=["1 MP", "2 MP", "4 MP"],
        default_value=0,
    )
    enhance_res.setHelp("Target resolution for Bria Enhance — improves image quality and detail")
    upscale_tab.addParmTemplate(enhance_res)

    enhance_btn = hou.ButtonParmTemplate("enhance_result", "Run Bria Enhance",
        script_callback="hou.phm().enhance_result_callback()",
        script_callback_language=hou.scriptLanguage.Python)
    enhance_btn.setHelp("Enhance the rendered result — improves quality and reduces artifacts")
    upscale_tab.addParmTemplate(enhance_btn)

    status = hou.StringParmTemplate("status", "Status", 1, default_value=["Ready"])
    upscale_tab.addParmTemplate(status)

    upscale_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_prompt"))

    ptg.append(upscale_tab)

    # --- Apply Texture tab ---
    apply_tab = hou.FolderParmTemplate("apply_texture_folder", "Apply Texture",
                                        folder_type=hou.folderType.Tabs)

    # Hidden parm to store the last AI result path (set by render_viewport callback)
    result_path = hou.StringParmTemplate("result_path", "Result Path", 1,
        default_value=[""], string_type=hou.stringParmType.FileReference)
    result_path.hide(True)
    apply_tab.addParmTemplate(result_path)

    source_img = hou.StringParmTemplate("source_image", "Source Image", 1,
        default_value=[""], string_type=hou.stringParmType.Regular)
    source_img.setHelp("Select a previously rendered Bria image to apply as texture")
    source_img.setMenuType(hou.menuType.StringReplace)
    source_img.setItemGeneratorScript('''
import os, glob, tempfile
try:
    from bria_houdini.bria_core.utils import resolve_temp_dir
    import hou
    output_dir = resolve_temp_dir(hou)
except Exception:
    output_dir = tempfile.gettempdir()
menu = []
if os.path.exists(output_dir):
    files = sorted(glob.glob(os.path.join(output_dir, "bria_render_*.png")),
                   key=os.path.getmtime, reverse=True)
    for f in files[:20]:
        name = os.path.basename(f)
        display = name.replace("bria_render_", "").replace(".png", "")
        menu.extend([f, display])
if not menu:
    menu = ["", "(No images found)"]
return menu
''')
    source_img.setItemGeneratorScriptLanguage(hou.scriptLanguage.Python)
    apply_tab.addParmTemplate(source_img)

    apply_tab.addParmTemplate(hou.ButtonParmTemplate("refresh_images", "Refresh Image List",
        script_callback="hou.phm().refresh_image_list_callback()",
        script_callback_language=hou.scriptLanguage.Python))

    apply_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_apply1"))

    apply_btn = hou.ButtonParmTemplate("apply_texture", "Apply Texture",
        script_callback="hou.phm().apply_texture_callback()",
        script_callback_language=hou.scriptLanguage.Python)
    apply_tab.addParmTemplate(apply_btn)

    apply_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_apply2"))

    pbr = hou.ToggleParmTemplate("use_pbr", "Use PBR Material", default_value=False)
    pbr.setHelp("OFF = OpenGL shader (viewport only). ON = Principled Shader (renderable).")
    apply_tab.addParmTemplate(pbr)

    ptg.append(apply_tab)

    # --- Settings tab ---
    settings = hou.FolderParmTemplate("settings", "Settings", folder_type=hou.folderType.Tabs)

    guidance = hou.IntParmTemplate("guidance_scale", "Guidance Scale", 1,
        default_value=[5], min=1, max=20, min_is_strict=True, max_is_strict=True)
    guidance.setHelp("How strongly the edit follows the instruction (1-20)")
    settings.addParmTemplate(guidance)

    settings.addParmTemplate(hou.SeparatorParmTemplate("sep_settings"))

    seed = hou.IntParmTemplate("seed", "Seed", 1, default_value=[0],
        min=0, max=2147483647, min_is_strict=True)
    seed.setHelp("Random seed for reproducible results (0 = random)")
    settings.addParmTemplate(seed)

    settings.addParmTemplate(hou.SeparatorParmTemplate("sep_settings2"))

    use_cache_parm = hou.ToggleParmTemplate("use_cache", "Use Cache", default_value=True)
    use_cache_parm.setHelp("When ON, identical requests may return cached results faster. Turn OFF to force a fresh generation every time.")
    settings.addParmTemplate(use_cache_parm)

    settings.addParmTemplate(hou.SeparatorParmTemplate("sep_advanced_toggle"))

    show_adv = hou.ToggleParmTemplate("show_advanced", "Show Advanced Settings", default_value=False)
    show_adv.setHelp("Reveal additional parameters for power users")
    settings.addParmTemplate(show_adv)

    steps_parm = hou.IntParmTemplate("steps_num", "Inference Steps", 1,
        default_value=[0], min=0, max=50, min_is_strict=True, max_is_strict=True)
    steps_parm.setHelp(
        "Override the number of AI denoising steps. Leave at 0 to use Bria's optimized default. "
        "Advanced users can set 25-50 for experimentation — higher values produce more detail but take longer."
    )
    steps_parm.setConditional(hou.parmCondType.HideWhen, '{ show_advanced == 0 }')
    settings.addParmTemplate(steps_parm)

    ptg.append(settings)

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate("info_hda", "HDA:", column_labels=["Bria Viewport Render v2.0"]))
    info.addParmTemplate(hou.LabelParmTemplate("info_desc", "", column_labels=["Captures viewport and renders with Bria AI (FIBO Edit)"]))
    ptg.append(info)

    # --- Advanced tab (shared — hidden from UI, parms still readable by code) ---
    _add_advanced_folder(ptg)

    hda_def.setParmTemplateGroup(ptg)

    # --- PythonModule ---
    pymod = _load_pymodule("bria_viewport_render.py")
    hda_def.addSection("PythonModule", pymod)
    hda_def.setExtraFileOption("PythonModule/IsPython", True)

    # --- Icon ---
    try:
        hda_def.setIcon("ROP_mantra")
    except Exception:
        pass

    # --- Save, install, set TAB menu ---
    hda_def.save(hda_file, template_node=hda_node)
    hou.hda.installFile(hda_file)

    _set_tool_submenu(hda_def, "Bria AI")
    hda_def.save(hda_file)
    hou.hda.installFile(hda_file)

    # Hide inherited OBJ tabs via DialogScript (hide()/setConditional() don't persist)
    import re
    hda_def = hou.hda.definitionsInFile(hda_file)[0]
    ds_section = hda_def.sections().get("DialogScript")
    if ds_section:
        ds = ds_section.contents()
        for tab_name in ("stdswitcher5", "stdswitcher5_1", "stdswitcher5_2"):
            ds = re.sub(r'(name\s+"' + tab_name + r'")', r'\1\n\tinvisible', ds)
        ds_section.setContents(ds)
        hda_def.save(hda_file)
        hou.hda.installFile(hda_file)
        print("  Inherited OBJ tabs hidden via DialogScript")

    # --- Cleanup ---
    try:
        hda_node.destroy()
    except Exception:
        pass
    temp_parent = obj.node("_bria_vr_builder_temp")
    if temp_parent:
        try:
            temp_parent.destroy()
        except Exception:
            pass

    if os.path.exists(hda_file):
        size = os.path.getsize(hda_file)
        # Check Object category
        obj_cat = hou.nodeTypeCategories().get("Object")
        found = any("bria_viewport_render" in t for t in obj_cat.nodeTypes()) if obj_cat else False
        status = "Object OK" if found else "CHECK CATEGORY"
        print(f"  OK: bria_viewport_render_v2 -> {hda_file} ({size} bytes) [{status}]")
    else:
        print(f"  FAILED: {hda_file} not created!")


# ===================================================================
# 12. BRIA FIBO EDIT TOP (PDG/TOPs batch processing)
# ===================================================================

def build_top_bria_batch():
    """Build the unified Bria Batch HDA for PDG batch processing.

    Supports all Bria API operations: FIBO Generate, FIBO Edit, Enhancer,
    Upscale, and Remove Background. A Mode dropdown controls which API is
    called and which parameters are visible.

    Uses SideFX's savehda._saveToHDA() directly — the exact same code path
    Houdini uses when saving a Python Processor as an HDA via the UI dialog.
    """
    from pdg.hda import savehda

    print("\n--- Building Bria Batch TOP ---")

    hda_file = os.path.join(HDAS_DIR, "bria_batch.hda")
    name = "bria_batch"
    label = "Bria Batch"

    # --- Cleanup existing (both old and new names) ---
    for old_name, old_file_name in [
        ("bria_batch", "bria_batch.hda"),
        ("bria_ai_top", "bria_ai_top.hda"),
        ("bria_top_fibo_edit", "bria_top_fibo_edit.hda"),
    ]:
        old_file = os.path.join(HDAS_DIR, old_file_name)
        if os.path.exists(old_file):
            try:
                hou.hda.uninstallFile(old_file)
            except Exception:
                pass
            try:
                for defn in hou.hda.definitionsInFile(old_file):
                    defn.destroy()
            except Exception:
                pass
            try:
                os.remove(old_file)
            except Exception:
                pass

        top_cat = hou.nodeTypeCategories().get("Top")
        if top_cat:
            for type_name in list(top_cat.nodeTypes().keys()):
                if old_name in type_name:
                    try:
                        node_type = top_cat.nodeTypes()[type_name]
                        for defn in node_type.allInstalledDefinitions():
                            print(f"  Uninstalling old definition: {type_name}")
                            defn.destroy()
                    except Exception:
                        pass

    # --- Create a real pythonprocessor with our callback code ---
    obj = hou.node("/obj")
    temp = obj.node("_bria_top_builder_temp")
    if temp:
        temp.destroy()
    topnet = obj.createNode("topnet", "_bria_top_builder_temp")
    pp = topnet.createNode("pythonprocessor", name)

    # Set onGenerate callback body
    generate_body = (
        "from bria_houdini.nodes.top_bria_batch import generate_work_items\n"
        "generate_work_items(self, item_holder, upstream_items, generation_type)"
    )
    pp.parm("generate").set(generate_body)

    # Set onCookTask callback body
    cooktask_body = (
        "from bria_houdini.nodes.top_bria_batch import cook_work_item\n"
        "cook_work_item(self, work_item)"
    )
    pp.parm("cooktask").set(cooktask_body)

    # --- Batch preset menu data (subset of FIBO Edit Recipes) ---
    _BATCH_CATEGORIES = [
        ("style",          "Style"),
        ("weather",        "Weather"),
        ("seasons",        "Seasons"),
        ("time_of_day",    "Time of Day"),
        ("camera",         "Camera"),
        ("lighting",       "Lighting"),
        ("clean",          "Clean / Artifacts"),
        ("ai_corrections", "AI Corrections"),
        ("object_edits",   "Object Edits"),
    ]
    _BATCH_PRESET_MENUS = {
        "style": [
            ("hand_drawn_classic",      "Hand-Drawn Classic"),
            ("3d_animated",             "3D Animated"),
            ("japanese_fantasy_anime",  "Japanese Fantasy Anime"),
            ("cel_shaded_anime",        "Cel-Shaded Anime"),
            ("film_noir",               "Film Noir"),
            ("aaa_game",                "AAA Game"),
            ("blockbuster_cinematic",   "Blockbuster Cinematic"),
            ("indie_film",              "Indie Film"),
            ("tv_sitcom",               "TV Sitcom"),
            ("oil_painting",            "Oil Painting"),
            ("watercolor",              "Watercolor"),
            ("comic_book",              "Comic Book"),
            ("pencil_sketch",           "Pencil Sketch"),
            ("retro_pixel",             "Retro Pixel Art"),
            ("cyberpunk",               "Cyberpunk"),
            ("steampunk",               "Steampunk"),
            ("pop_art",                 "Pop Art"),
            ("art_nouveau",             "Art Nouveau"),
        ],
        "weather": [
            ("sunny_clear",  "Sunny & Clear"),
            ("overcast",     "Overcast"),
            ("rainy",        "Rainy"),
            ("thunderstorm", "Thunderstorm"),
            ("snowy",        "Snowy"),
            ("foggy",        "Foggy / Misty"),
            ("windy",        "Windy"),
            ("hazy_humid",   "Hazy / Humid"),
        ],
        "seasons": [
            ("spring", "Spring"),
            ("summer", "Summer"),
            ("autumn", "Autumn"),
            ("winter", "Winter"),
        ],
        "time_of_day": [
            ("dawn",        "Dawn"),
            ("morning",     "Morning"),
            ("golden_hour", "Golden Hour"),
            ("midday",      "Midday"),
            ("blue_hour",   "Blue Hour"),
            ("dusk",        "Dusk"),
            ("night",       "Night"),
            ("starry_night","Starry Night"),
        ],
        "camera": [
            ("shallow_dof",   "Shallow Depth of Field"),
            ("tilt_shift",    "Tilt Shift"),
            ("wide_angle",    "Wide Angle"),
            ("macro_closeup", "Macro Close-Up"),
            ("birds_eye",     "Bird's Eye View"),
            ("dutch_angle",   "Dutch Angle"),
            ("long_exposure", "Long Exposure"),
            ("fisheye",       "Fisheye"),
        ],
        "lighting": [
            ("dramatic_side",      "Dramatic Side Light"),
            ("rim_backlight",      "Rim / Backlight"),
            ("soft_diffused",      "Soft Diffused"),
            ("neon_glow",          "Neon Glow"),
            ("candlelight",        "Candlelight"),
            ("studio_three_point", "Studio Three-Point"),
            ("volumetric_rays",    "Volumetric Rays"),
            ("harsh_flash",        "Harsh Flash"),
        ],
        "clean": [
            ("color_correction",            "Color Correction"),
            ("gamma_correction",            "Gamma Correction"),
            ("fix_artifacts",               "Fix Artifacts"),
            ("remove_noise",                "Remove Noise"),
            ("sharpen",                     "Sharpen"),
            ("fix_white_balance",           "Fix White Balance"),
            ("fix_exposure",                "Fix Exposure"),
            ("reduce_chromatic_aberration", "Fix Chromatic Aberration"),
        ],
        "ai_corrections": [
            ("fix_face",                 "Fix Face Distortion"),
            ("fix_eyes",                 "Fix Eyes"),
            ("fix_hands",                "Fix Hands & Fingers"),
            ("fix_teeth_mouth",          "Fix Teeth & Mouth"),
            ("fix_body_anatomy",         "Fix Body Anatomy"),
            ("fix_skin_texture",         "Fix Skin Texture"),
            ("fix_hair",                 "Fix Hair"),
            ("fix_background_coherence", "Fix Background Coherence"),
        ],
        "object_edits": [
            ("add_vegetation",       "Add Vegetation"),
            ("add_people",           "Add People"),
            ("add_clouds",           "Add Clouds"),
            ("remove_people",        "Remove People"),
            ("add_water_reflection", "Add Water Reflection"),
            ("age_weathering",       "Add Aging / Weathering"),
            ("modernize",            "Modernize"),
            ("add_text_overlay",     "Add Text Overlay"),
        ],
    }

    # --- Add custom parms with mode-conditional visibility ---
    ptg = pp.parmTemplateGroup()

    # HideWhen conditions (multiple braces = AND: all must be true to hide)
    _HIDE_NOT_GEN = '{ mode != "generate" }'
    _HIDE_NOT_EDIT = '{ mode != "edit" }'
    _HIDE_NOT_ENHANCER = '{ mode != "enhancer" }'
    _HIDE_NOT_UPSCALE = '{ mode != "upscale" }'
    _HIDE_NOT_RMBG = '{ mode != "rmbg" }'
    _HIDE_NO_PROMPT = '{ mode != "generate" mode != "edit" }'
    _HIDE_NO_GUIDANCE = '{ mode != "generate" mode != "edit" }'
    _HIDE_NO_STEPS = '{ mode != "generate" mode != "edit" mode != "enhancer" }'
    _HIDE_NO_MODERATION = '{ mode != "enhancer" mode != "upscale" mode != "rmbg" }'
    _HIDE_NO_ALPHA = '{ mode != "enhancer" mode != "upscale" mode != "rmbg" }'

    # ---- API warning ----
    warn_label = hou.LabelParmTemplate(
        "api_warning", "",
        column_labels=["WARNING: Running this node will launch multiple API calls"],
    )
    ptg.addParmTemplate(warn_label)
    ptg.addParmTemplate(hou.SeparatorParmTemplate("warn_sep"))

    # ---- Mode selector ----
    mode_parm = hou.MenuParmTemplate(
        "mode", "Mode",
        menu_items=["generate", "edit", "enhancer", "upscale", "rmbg"],
        menu_labels=["FIBO Generate", "FIBO Edit", "Enhancer", "Upscale", "Remove Background"],
        default_value=1,  # Default to Edit (most common batch use case)
    )
    mode_parm.setHelp("Select which Bria API operation to run on each work item.")
    ptg.addParmTemplate(mode_parm)

    ptg.addParmTemplate(hou.SeparatorParmTemplate("sep_mode"))

    # ---- Prompt section (Generate, Edit) ----
    prompt_parm = hou.StringParmTemplate("prompt", "Prompt", 1, default_value=[""])
    prompt_parm.setTags({"editor": "1", "editorLines": "4"})
    prompt_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NO_PROMPT)
    ptg.addParmTemplate(prompt_parm)

    # ---- Prompt Mode toggle (Custom vs Preset) — Edit mode only ----
    prompt_mode_parm = hou.MenuParmTemplate(
        "prompt_mode", "Prompt Mode",
        menu_items=["custom", "preset"],
        menu_labels=["Custom", "Preset"],
        default_value=0,
        script_callback="hou.phm().on_prompt_mode_changed(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    prompt_mode_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_EDIT)
    ptg.addParmTemplate(prompt_mode_parm)

    # ---- Batch category menu (visible in Edit + Preset mode) ----
    # Multiple {} blocks = OR: hidden when ANY condition is true
    _HIDE_NOT_PRESET = '{ mode != "edit" } { prompt_mode != "preset" }'

    bcat_tokens = [tok for tok, _ in _BATCH_CATEGORIES]
    bcat_labels = [lbl for _, lbl in _BATCH_CATEGORIES]
    batch_cat_menu = hou.MenuParmTemplate(
        "batch_category", "Category",
        menu_items=bcat_tokens,
        menu_labels=bcat_labels,
        default_value=0,
        script_callback="hou.phm().on_batch_category_changed(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    batch_cat_menu.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_PRESET)
    ptg.addParmTemplate(batch_cat_menu)

    # ---- Per-category preset menus ----
    for bcat_tok, _ in _BATCH_CATEGORIES:
        bpresets = _BATCH_PRESET_MENUS.get(bcat_tok, [])
        if not bpresets:
            continue
        bp_tokens = [p[0] for p in bpresets]
        bp_labels = [p[1] for p in bpresets]
        bpreset_menu = hou.MenuParmTemplate(
            f"batch_preset_{bcat_tok}", "Preset",
            menu_items=bp_tokens,
            menu_labels=bp_labels,
            default_value=0,
            script_callback="hou.phm().on_batch_preset_changed(kwargs)",
            script_callback_language=hou.scriptLanguage.Python,
        )
        bpreset_menu.setConditional(
            hou.parmCondType.HideWhen,
            _HIDE_NOT_PRESET + ' { batch_category != "' + bcat_tok + '" }'
        )
        ptg.addParmTemplate(bpreset_menu)

    neg_parm = hou.StringParmTemplate(
        "negative_prompt", "Negative Prompt", 1, default_value=[""],
    )
    neg_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NO_PROMPT)
    ptg.addParmTemplate(neg_parm)

    sp_parm = hou.StringParmTemplate(
        "structured_prompt", "Structured Prompt (JSON)", 1, default_value=[""],
    )
    sp_parm.setTags({"editor": "1", "editorLines": "6"})
    sp_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NO_PROMPT)
    ptg.addParmTemplate(sp_parm)

    # ---- Generate-specific ----
    num_images_parm = hou.IntParmTemplate(
        "num_images", "Num Images (no upstream)", 1,
        default_value=(1,), min=1, max=100,
        min_is_strict=True, max_is_strict=False,
    )
    num_images_parm.setHelp(
        "Number of images to generate when no upstream items are connected. "
        "With upstream items, one image is generated per upstream item."
    )
    num_images_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_GEN)
    ptg.addParmTemplate(num_images_parm)

    ar_parm = hou.MenuParmTemplate(
        "aspect_ratio", "Aspect Ratio",
        menu_items=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"],
        menu_labels=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"],
        default_value=0,
    )
    ar_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_GEN)
    ptg.addParmTemplate(ar_parm)

    pipe_parm = hou.MenuParmTemplate(
        "pipeline", "Pipeline",
        menu_items=["standard", "lite"],
        menu_labels=["Standard", "Lite"],
        default_value=0,
    )
    pipe_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_GEN)
    ptg.addParmTemplate(pipe_parm)

    # ---- Enhancer-specific ----
    res_parm = hou.MenuParmTemplate(
        "resolution", "Resolution",
        menu_items=["1MP", "2MP", "4MP"],
        menu_labels=["1 Megapixel", "2 Megapixels", "4 Megapixels"],
        default_value=0,
    )
    res_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_ENHANCER)
    ptg.addParmTemplate(res_parm)

    # ---- Upscale-specific ----
    dr_parm = hou.MenuParmTemplate(
        "desired_resolution", "Desired Resolution",
        menu_items=["2x", "4x"],
        menu_labels=["2x", "4x"],
        default_value=0,
    )
    dr_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_UPSCALE)
    ptg.addParmTemplate(dr_parm)

    # ---- RMBG-specific ----
    kos_parm = hou.ToggleParmTemplate(
        "keep_original_size", "Keep Original Size", default_value=True,
    )
    kos_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_RMBG)
    ptg.addParmTemplate(kos_parm)

    fbg_parm = hou.ToggleParmTemplate(
        "force_bg_detection", "Force Background Detection", default_value=False,
    )
    fbg_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NOT_RMBG)
    ptg.addParmTemplate(fbg_parm)

    # ---- Common API parameters ----
    ptg.addParmTemplate(hou.SeparatorParmTemplate("sep_api"))

    gs_parm = hou.IntParmTemplate(
        "guidance_scale", "Guidance Scale", 1,
        default_value=(5,), min=1, max=20,
        min_is_strict=True, max_is_strict=True,
    )
    gs_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NO_GUIDANCE)
    ptg.addParmTemplate(gs_parm)

    ptg.addParmTemplate(hou.IntParmTemplate(
        "seed", "Seed (0 = random)", 1,
        default_value=(0,), min=0, max=2147483647,
        min_is_strict=True, max_is_strict=True,
    ))

    steps_parm = hou.IntParmTemplate(
        "steps_num", "Inference Steps (0 = default)", 1,
        default_value=(0,), min=0, max=50,
        min_is_strict=True, max_is_strict=True,
    )
    steps_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NO_STEPS)
    ptg.addParmTemplate(steps_parm)

    pa_parm = hou.ToggleParmTemplate(
        "preserve_alpha", "Preserve Alpha", default_value=True,
    )
    pa_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NO_ALPHA)
    ptg.addParmTemplate(pa_parm)

    cm_in_parm = hou.ToggleParmTemplate(
        "content_moderation_input", "Content Moderation (Input)", default_value=False,
    )
    cm_in_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NO_MODERATION)
    ptg.addParmTemplate(cm_in_parm)

    cm_out_parm = hou.ToggleParmTemplate(
        "content_moderation_output", "Content Moderation (Output)", default_value=False,
    )
    cm_out_parm.setConditional(hou.parmCondType.HideWhen, _HIDE_NO_MODERATION)
    ptg.addParmTemplate(cm_out_parm)

    # ---- Workflow ----
    ptg.addParmTemplate(hou.SeparatorParmTemplate("sep_workflow"))

    max_concurrent_parm = hou.IntParmTemplate(
        "max_concurrent", "Max Concurrent Tasks", 1,
        default_value=(4,), min=1, max=32,
        min_is_strict=True, max_is_strict=False,
    )
    max_concurrent_parm.setHelp(
        "Maximum simultaneous API calls. Lower this if you hit rate limits. "
        "Default 4 is safe for most Bria API plans."
    )
    ptg.addParmTemplate(max_concurrent_parm)

    # --- Output naming ---
    output_dir_parm = hou.StringParmTemplate(
        "output_dir", "Output Directory", 1,
        default_value=[""],
        string_type=hou.stringParmType.FileReference,
    )
    output_dir_parm.setHelp(
        "Directory for output files. Leave empty to use temp dir."
    )
    ptg.addParmTemplate(output_dir_parm)

    output_suffix_parm = hou.StringParmTemplate(
        "output_suffix", "Output Suffix", 1,
        default_value=[""],
    )
    output_suffix_parm.setHelp(
        "Suffix appended to input filename (e.g. '__sketch1'). "
        "Leave empty to keep default auto-generated names."
    )
    ptg.addParmTemplate(output_suffix_parm)

    mplay_parm = hou.ToggleParmTemplate(
        "open_in_mplay", "Open Results in MPlay", default_value=True,
    )
    mplay_parm.setHelp(
        "Send each completed result to a shared MPlay window. "
        "Images appear as sequential frames for easy review."
    )
    ptg.addParmTemplate(mplay_parm)

    pp.setParmTemplateGroup(ptg)
    print("  Created pythonprocessor with mode-conditional parms")

    # --- Let SideFX's _saveToHDA do all the heavy lifting ---
    savehda._saveToHDA(pp, name, label, hda_file, "Bria AI")
    print("  _saveToHDA complete")

    # --- Cleanup temp topnet ---
    try:
        topnet.destroy()
    except Exception:
        pass

    # --- Install and diagnose/fix PythonModule callbacks ---
    hou.hda.installFile(hda_file)

    defs = hou.hda.definitionsInFile(hda_file)
    if not defs:
        print(f"  FAILED: no definitions found in {hda_file}")
        return

    hda_def = defs[0]
    sections = hda_def.sections()

    # Diagnostic: dump all HDA sections
    print("  HDA sections after _saveToHDA:")
    for sec_name in sorted(sections.keys()):
        content = sections[sec_name].contents()
        preview = content.split("\n")[0][:80] if content else "(empty)"
        print(f"    [{sec_name}] ({len(content)} chars): {preview}")

    pm_section = sections.get("PythonModule")
    if pm_section:
        print("  --- PythonModule from _saveToHDA ---")
        for line in pm_section.contents().split("\n"):
            print(f"    | {line}")
        print("  --- end PythonModule ---")

    # Verify _saveToHDA embedded callbacks. Only patch if missing.
    pm_code = pm_section.contents() if pm_section else ""
    has_generate = "onGenerate" in pm_code
    has_cook = "onCookTask" in pm_code
    has_presets = "on_prompt_mode_changed" in pm_code
    if has_generate and has_cook and has_presets:
        print("  PythonModule OK — onGenerate + onCookTask + preset callbacks verified")
    else:
        missing = []
        if not has_generate:
            missing.append("onGenerate")
        if not has_cook:
            missing.append("onCookTask")
        if not has_presets:
            missing.append("preset callbacks")
        print(f"  WARNING: _saveToHDA missing {', '.join(missing)} — patching")
        correct_pm = textwrap.dedent("""\
            import hou
            import pdg
            from bria_houdini.nodes.top_bria_batch import (
                generate_work_items, cook_work_item,
                on_prompt_mode_changed, on_batch_category_changed,
                on_batch_preset_changed,
            )

            def onGenerate(self, item_holder, upstream_items, generation_type):
                generate_work_items(self, item_holder, upstream_items, generation_type)
                return pdg.result.Success

            def onCookTask(self, work_item):
                cook_work_item(self, work_item)
                return pdg.result.Success
        """)
        if pm_section:
            pm_section.setContents(correct_pm)
        else:
            hda_def.addSection("PythonModule", correct_pm)
        hda_def.save(hda_file)
        print("  PythonModule patched and saved")

    # Set icon and TAB menu category (must happen after save+install)
    try:
        hda_def.setIcon("TOP_ropcomposite")
    except Exception:
        pass
    _set_tool_submenu(hda_def, "Bria AI")
    hda_def.save(hda_file)
    hou.hda.installFile(hda_file)

    if os.path.exists(hda_file):
        size = os.path.getsize(hda_file)
        top_cat = hou.nodeTypeCategories().get("Top")
        found = any(name in t for t in top_cat.nodeTypes()) if top_cat else False
        status = "Top OK" if found else "CHECK CATEGORY"
        print(f"  OK: {name} -> {hda_file} ({size} bytes) [{status}]")
    else:
        print(f"  FAILED: {hda_file} not created!")


# ===================================================================
# 13. BRIA SEQUENCE OUTPUT (COP — batch render through Bria chain)
# ===================================================================

def build_sequence_output():
    print("\n--- Building Bria Sequence Output ---")

    hda_file = os.path.join(HDAS_DIR, "bria_sequence_output.hda")
    _remove_existing(hda_file, base_name="bria_sequence_output")

    hda_node, cop_net = _build_cop_hda(
        "bria_sequence_output", "Bria Sequence Output", "1.0", hda_file, num_inputs=1,
    )
    hda_def = hda_node.type().definition()

    ptg = hou.ParmTemplateGroup()

    # --- Render tab ---
    render_tab = hou.FolderParmTemplate("render", "Render", folder_type=hou.folderType.Tabs)

    # Frame range
    render_tab.addParmTemplate(hou.IntParmTemplate(
        "frame_start", "Start Frame", 1,
        default_expression=("$FSTART",),
        default_expression_language=(hou.scriptLanguage.Hscript,),
    ))
    render_tab.addParmTemplate(hou.IntParmTemplate(
        "frame_end", "End Frame", 1,
        default_expression=("$FEND",),
        default_expression_language=(hou.scriptLanguage.Hscript,),
    ))
    render_tab.addParmTemplate(hou.IntParmTemplate(
        "frame_step", "Frame Step", 1,
        default_value=(1,), min=1, max=100,
        min_is_strict=True, max_is_strict=False,
    ))

    render_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_output"))

    # Output path
    op_parm = hou.StringParmTemplate(
        "output_path", "Output Path", 1,
        default_value=["$HIP/render/$HIPNAME.$OS.$F4.png"],
        string_type=hou.stringParmType.FileReference,
    )
    op_parm.setTags({"filechooser_pattern": "*.png *.jpg *.exr"})
    render_tab.addParmTemplate(op_parm)

    render_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_render_btn"))

    # Render button
    render_btn = hou.ButtonParmTemplate(
        "render_sequence", "Render Bria Sequence To Disk",
        script_callback="hou.phm().on_render(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    render_tab.addParmTemplate(render_btn)

    render_tab.addParmTemplate(hou.SeparatorParmTemplate("sep_chain"))

    # Refresh chain + chain info
    refresh_btn = hou.ButtonParmTemplate(
        "refresh_chain", "Refresh Chain Info",
        script_callback="hou.phm().on_refresh_chain(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    render_tab.addParmTemplate(refresh_btn)

    ci_parm = hou.StringParmTemplate(
        "chain_info", "Chain Info", 1,
        default_value=["(click Refresh Chain Info)"],
    )
    ci_parm.setConditional(hou.parmCondType.DisableWhen, "{ chain_info != __never_match__ }")
    render_tab.addParmTemplate(ci_parm)

    # Status (live progress during render)
    st_parm = hou.StringParmTemplate(
        "status", "Status", 1, default_value=[""],
    )
    st_parm.setConditional(hou.parmCondType.DisableWhen, "{ status != __never_match__ }")
    render_tab.addParmTemplate(st_parm)

    ptg.append(render_tab)

    # --- Info tab ---
    info = hou.FolderParmTemplate("info", "Info", folder_type=hou.folderType.Tabs)
    info.addParmTemplate(hou.LabelParmTemplate(
        "info_hda", "HDA:", column_labels=["Bria Sequence Output v1.0"],
    ))
    info.addParmTemplate(hou.LabelParmTemplate(
        "info_about", "About:", column_labels=[
            "Batch render a COP chain with Bria AI nodes. "
            "Place at the end of your comp, set frame range and output path, "
            "then click Render."
        ],
    ))
    ptg.append(info)

    # result_path parm (hidden, required by _wire_internals for pass-through wiring)
    rp = hou.StringParmTemplate("result_path", "Result Path", 1, default_value=[""])
    rp.hide(True)
    ptg.append(rp)

    hda_def.setParmTemplateGroup(ptg)

    try:
        hda_def.setIcon("ROP_mantra")
    except Exception:
        pass

    pymod = _load_pymodule("bria_sequence_output.py")
    _finalize(hda_node, hda_def, hda_file, pymod, cop_net, "bria_sequence_output")


# ===================================================================
# MAIN
# ===================================================================

def build_all():
    print("=" * 50)
    print("Bria New HDA Builder")
    print("=" * 50)

    build_enhancer()
    build_fibo_edit()
    build_fibo_edit_recipes()
    build_generate_structured_prompt()
    build_generate_image()
    build_expand()
    build_rmbg()
    build_erase()
    build_upscale()
    build_genfill()
    build_viewport_render()
    build_top_bria_batch()
    build_sequence_output()

    print("\n" + "=" * 50)
    print("ALL 13 HDAs BUILT!")
    print("=" * 50)
    print("\nNew HDAs saved to:", HDAS_DIR)
    print("\nTo use: restart Houdini (if Bria package is installed),")
    print("then tab-search for:")
    print("  - Bria Enhancer")
    print("  - Bria FIBO Edit")
    print("  - Bria FIBO Edit Recipes")
    print("  - Bria Generate VGL")
    print("  - Bria FIBO Generate")
    print("  - Bria Expand")
    print("  - Bria RMBG")
    print("  - Bria Erase")
    print("  - Bria Upscale")
    print("  - Bria GenFill")
    print("  - Bria Viewport Render")
    print("  - Bria Batch (TOP) — unified batch processor")
    print("  - Bria Sequence Output (COP) — batch render through Bria chain")


# To build everything:    exec(open("build_new_hdas.py").read()); build_all()
# To build just the TOP:  exec(open("build_new_hdas.py").read()); build_top_bria_batch()
#
# Uncomment the next line to auto-build all on exec():
build_all()
