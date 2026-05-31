# POSIX equivalent of the old _build.bat / _deploy.bat / _release.ps1.
#
# On macOS the calibre CLI tools live inside the app bundle; override
# CALIBRE_CUSTOMIZE / CALIBRE_DEBUG in the environment if your install
# lives somewhere else.

ifeq ($(shell uname),Darwin)
CALIBRE_CUSTOMIZE ?= /Applications/calibre.app/Contents/MacOS/calibre-customize
CALIBRE_DEBUG     ?= /Applications/calibre.app/Contents/MacOS/calibre-debug
else
CALIBRE_CUSTOMIZE ?= calibre-customize
CALIBRE_DEBUG     ?= calibre-debug
endif

ZIP_NAME    := remarkable-calibre-usb-device.zip
RELEASE_DIR := release

# Patterns excluded from the released plugin zip.
ZIP_EXCLUDES := \
	'.git/*' \
	'.github/*' \
	'img/*' \
	'$(RELEASE_DIR)/*' \
	'__pycache__/*' \
	'*.pyc' \
	'.gitignore' \
	'.pre-commit-config.yaml' \
	'Makefile' \
	'PLAN.md' \
	'pyproject.toml' \
	'poetry.lock' \
	'upload_book.sh'

.PHONY: help build deploy release clean

help:
	@echo "Targets:"
	@echo "  build    - register the plugin with Calibre from this directory"
	@echo "  deploy   - build, then launch Calibre in GUI debug mode"
	@echo "  release  - produce $(RELEASE_DIR)/$(ZIP_NAME)"
	@echo "  clean    - remove $(RELEASE_DIR)/"

build:
	$(CALIBRE_CUSTOMIZE) -b .

deploy: build
	$(CALIBRE_DEBUG) -g

release: clean
	mkdir -p $(RELEASE_DIR)
	zip -r $(RELEASE_DIR)/$(ZIP_NAME) . -x $(ZIP_EXCLUDES)

clean:
	rm -rf $(RELEASE_DIR)
