"""
Bria Installer HDA Builder
Creates a self-contained installer HDA at the bria-houdini repo root.

Run in Houdini Python Shell:
    exec(open("<repo>/bria_houdini/builders/build_installer_hda.py").read())
"""

import hou
import os

# Resolve repo root relative to this script's location.
def _find_repo_root():
    if "__file__" in dir() and os.path.basename(__file__) == "build_installer_hda.py":
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    env = os.environ.get("BRIA_HOUDINI_REPO")
    if env and os.path.isdir(env):
        return env
    for candidate in [os.getcwd(), os.path.expanduser("~/Desktop/Houdini_Tool_Release"),
                      os.path.expanduser("~/Desktop/Bria_Dev/bria-houdini")]:
        if os.path.isfile(os.path.join(candidate, "bria_houdini", "builders", "build_installer_hda.py")):
            return candidate
    return os.getcwd()

_REPO_ROOT = _find_repo_root()

# Configuration
HDA_NAME = "bria_installer"
HDA_LABEL = "Bria Installer"
HDA_VERSION = "1.0.0"
HDA_FILE = os.path.join(_REPO_ROOT, "bria_installer.hda")

# The PythonModule script — read from the file we already created
PYTHON_MODULE_FILE = os.path.join(_REPO_ROOT, "scripts", "installer_pythonmodule.py")


def build_installer_hda():
    print("=" * 50)
    print("Bria Installer HDA Builder")
    print("=" * 50)

    # Remove existing HDA if present
    if os.path.exists(HDA_FILE):
        print("\nRemoving existing HDA...")
        try:
            for defn in hou.hda.definitionsInFile(HDA_FILE):
                defn.destroy()
        except:
            pass
        try:
            os.remove(HDA_FILE)
        except:
            pass

    # Create temp subnet at OBJ level
    print("\nStep 1: Creating temporary network...")
    obj = hou.node("/obj")

    temp_net = obj.node("_bria_installer_temp")
    if temp_net:
        temp_net.destroy()

    subnet = obj.createNode("subnet", "_bria_installer_temp")
    print(f"  Created: {subnet.path()}")

    # Create HDA from subnet
    print("\nStep 2: Creating HDA...")
    hda_node = subnet.createDigitalAsset(
        name=HDA_NAME,
        hda_file_name=HDA_FILE,
        description=HDA_LABEL,
        min_num_inputs=0,
        max_num_inputs=0,
        version=HDA_VERSION,
    )
    print(f"  Created: {hda_node.type().name()}")

    hda_def = hda_node.type().definition()

    # Build parameters
    print("\nStep 3: Adding parameters...")
    ptg = hou.ParmTemplateGroup()

    # Info label at top
    info_label = hou.LabelParmTemplate(
        "info_label", "",
        column_labels=["Bria Houdini Tools Installer"],
    )
    ptg.append(info_label)

    ptg.append(hou.SeparatorParmTemplate("sep1"))

    # Get API Key button
    get_key_btn = hou.ButtonParmTemplate(
        "get_api_key", "Get API Key",
        script_callback="hou.phm().open_api_keys(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    get_key_btn.setHelp("Opens Bria console in your browser to get an API key")
    ptg.append(get_key_btn)

    # API Key input
    api_key_parm = hou.StringParmTemplate(
        "api_key", "API Key", 1,
        default_value=[""],
    )
    api_key_parm.setHelp("Paste your Bria API key here")
    ptg.append(api_key_parm)

    ptg.append(hou.SeparatorParmTemplate("sep2"))

    # Install button
    install_btn = hou.ButtonParmTemplate(
        "install", "Install",
        script_callback="hou.phm().install(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    install_btn.setHelp("Install Bria tools and save API key")
    ptg.append(install_btn)

    # Uninstall button
    uninstall_btn = hou.ButtonParmTemplate(
        "uninstall", "Uninstall",
        script_callback="hou.phm().uninstall(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
    )
    uninstall_btn.setHelp("Remove Bria tools and API key")
    ptg.append(uninstall_btn)

    ptg.append(hou.SeparatorParmTemplate("sep3"))

    # Status display
    status_parm = hou.StringParmTemplate(
        "status", "Status", 1,
        default_value=["Not installed"],
    )
    status_parm.setHelp("Current installation status")
    status_parm.setConditional(
        hou.parmCondType.DisableWhen, "{ status != __never_match__ }"
    )
    ptg.append(status_parm)

    hda_def.setParmTemplateGroup(ptg)
    print("  Parameters added")

    # Load and embed PythonModule
    print("\nStep 4: Embedding PythonModule...")
    with open(PYTHON_MODULE_FILE, "r") as f:
        python_module = f.read()

    hda_def.addSection("PythonModule", python_module)
    hda_def.setExtraFileOption("PythonModule/IsPython", True)
    print(f"  Loaded from: {PYTHON_MODULE_FILE}")

    # Set icon
    try:
        hda_def.setIcon("MISC_python")
    except:
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

    # Install into current session
    print("\nStep 6: Installing into current session...")
    hou.hda.installFile(HDA_FILE)

    # Hide inherited OBJ subnet tabs — must happen after save+install
    print("\nStep 6b: Hiding inherited tabs...")
    hda_def = hou.hda.definitionsInFile(HDA_FILE)[0]
    ptg = hda_def.parmTemplateGroup()
    for tab_name in ("stdswitcher4", "stdswitcher4_1"):
        pt = ptg.find(tab_name)
        if pt is not None:
            pt.hide(True)
            ptg.replace(tab_name, pt)
    hda_def.setParmTemplateGroup(ptg)
    hda_def.save(HDA_FILE)
    hou.hda.installFile(HDA_FILE)
    print("  Inherited tabs hidden (Transform, Subnet)")

    obj_cat = hou.objNodeTypeCategory()
    if HDA_NAME in obj_cat.nodeTypes():
        print(f"  SUCCESS: '{HDA_NAME}' is available at OBJ level!")
    else:
        print(f"  Note: Node registered (check tab menu at /obj)")

    # Cleanup
    print("\nStep 7: Cleanup...")
    try:
        temp = obj.node("_bria_installer_temp")
        if temp:
            temp.destroy()
    except:
        pass  # Node may already be consumed by createDigitalAsset
    print("  Done")

    print("\n" + "=" * 50)
    print("BUILD COMPLETE!")
    print("=" * 50)
    print(f"\nTo use:")
    print(f"  1. Tab-search 'Bria Installer'")
    print(f"  2. Click 'Get API Key' to open Bria console")
    print(f"  3. Paste your key")
    print(f"  4. Click 'Install'")
    print(f"  5. Restart Houdini")

    return True


# Run
if __name__ == "__main__" or True:
    try:
        build_installer_hda()
    except Exception as e:
        print(f"\nBUILD FAILED: {e}")
        import traceback
        traceback.print_exc()
