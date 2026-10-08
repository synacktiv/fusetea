PROJNAME=python3-fusetea
VERSION_BASE      = $(shell cat VERSION)
PROJECT_REVISION  = $(shell git rev-list --count HEAD)
PROJECT_VERSION  ?= $(VERSION_BASE).$(PROJECT_REVISION)
PROJECT_DATE     ?= $(shell date --utc -R)

.PHONY: version
version:  ## Print the current version of the project
	@echo $(PROJECT_VERSION)

changelog:
	printf "fusetea ($(PROJECT_VERSION)) STABLE; urgency=low\n\n  * v$(PROJECT_VERSION)\n\n -- Louis Wolfers <firstname.lastname@synacktiv.com>  $(PROJECT_DATE)\n" > debian/changelog

deb: changelog
	dpkg-buildpackage -i -us -uc -b
	mv ../$(PROJNAME)_$(PROJECT_VERSION)_*.deb .
	# remove buildinfo & changes
	-@rm -f ../$(PROJNAME)_*.buildinfo ../$(PROJNAME)_*.changes ../$(PROJNAME)_*.build
