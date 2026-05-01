# Changelog

## [0.3.1](https://github.com/Bria-AI/Houdini-tools/compare/v0.1.0...v0.3.1) (2026-05-01)


### Features

* add Bria Sequence Output COP HDA ([ad1451c](https://github.com/Bria-AI/Houdini-tools/commit/ad1451c4a3dcf487e74fbe29b3d269d7900d779d))
* add Isolate Object preset to FIBO Edit Recipes ([7f6114f](https://github.com/Bria-AI/Houdini-tools/commit/7f6114f9bf61dc734379f39d44f59d70b42811ad))
* batch TOP confirmation popup and Lock VGL toggle ([a55867c](https://github.com/Bria-AI/Houdini-tools/commit/a55867c8546ce816c36bbb177ec03260bedd5afa))
* OnCreated script clears result_path, isolate_object menu, VGL prefix fix ([72650a2](https://github.com/Bria-AI/Houdini-tools/commit/72650a2372c794d156ca1cf80ba413c49fa83a24))


### Bug Fixes

* auto-inject objects field in structured prompts to prevent 422 errors ([9cb613b](https://github.com/Bria-AI/Houdini-tools/commit/9cb613ba30f865823fc0f70ba014464e1a1fb5d9))
* default output to $HIP project directory, add temp dir toggle ([0ff378b](https://github.com/Bria-AI/Houdini-tools/commit/0ff378b8054a171da6b9062480533a6331464507))
* installer writes correct path for Dashboard and shelf discovery ([cb9fa1f](https://github.com/Bria-AI/Houdini-tools/commit/cb9fa1fe6e0605aa9a60ca44f4021b8c8ac25031))
* Linux ROP permissions — allowEditingOfContents in cop_export ([083fb9e](https://github.com/Bria-AI/Houdini-tools/commit/083fb9e787ee22929aa0fb8cbda5055b3107dd94))
* remove duplicate lowercase changelog.md from git tree ([21fc7e5](https://github.com/Bria-AI/Houdini-tools/commit/21fc7e5b04afca64602611c61d82a01197f16e8b))
* save results to ~/Desktop/bria_houdini_tool_output/ when no project folder is set ([0e39902](https://github.com/Bria-AI/Houdini-tools/commit/0e39902c1deee2e98fcd0a090bd5c453d9d0410e))


### Documentation

* update to 13 HDAs, add Sequence Output, remove experimental section ([0069f50](https://github.com/Bria-AI/Houdini-tools/commit/0069f50d334a2c9a2e052be0de1697c713c6e403))


### Miscellaneous Chores

* changelog cleanups ([a5c3adc](https://github.com/Bria-AI/Houdini-tools/commit/a5c3adc75f5998c607c670afc2c0cd3968ffb4cd))

## 0.1.0 / 0.2.0 (2026-04-01)


### ⚠ BREAKING CHANGES

* imports changed from houdini.* to bria_houdini.*
* 12 production HDAs for Houdini 21

### Features

* 12 production HDAs for Houdini 21 ([2c113ba](https://github.com/Bria-AI/houdini-tools/commit/2c113baaaefa6c75afdf94b2b35175168b1b1019))
* User-Agent header (BriaHoudini/0.1.0) ([2c113ba](https://github.com/Bria-AI/houdini-tools/commit/2c113baaaefa6c75afdf94b2b35175168b1b1019))


### Bug Fixes

* builder scripts ([2c113ba](https://github.com/Bria-AI/houdini-tools/commit/2c113baaaefa6c75afdf94b2b35175168b1b1019))
* drop v1 endpoint fallbacks. All endpoints v2 only. ([2c113ba](https://github.com/Bria-AI/houdini-tools/commit/2c113baaaefa6c75afdf94b2b35175168b1b1019))


### Documentation

* renamed docs ([526caa3](https://github.com/Bria-AI/houdini-tools/commit/526caa3e62ba4afba8a18463454df82d71953366))


### Code Refactoring

* bug fixes, VGL rename, rebuilt HDAs, v0.2.0 ([106d85b](https://github.com/Bria-AI/houdini-tools/commit/106d85b013f25a528dfcaaec9650905fd5efe371))
