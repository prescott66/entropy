#!/usr/bin/python
# Copyright Fabio Erculiani - Sabayon Linux 2007

# DESCRIPTION:
# Variables container

# Specifications of the content of .etp file go here
pData = {
    'name': "", # the Package Name
    'version': "", # the Package version plus our -etpXX revision
    'description': "", # the Package description
    'category': "", # the gentoo category
    'chost': "", # the CHOST used to compile it
    'cflags': "", # CFLAGS used
    'cxxflags': "", # CXXFLAGS used
    'homepage': "", # home page of the package
    'useflags': "", # USE flags used
    'license': "", # License adpoted
    'keywords': "", # supported ARCHs
    'download': "", # link to download the binary package
    'sources': "", # link to the sources
    'dependencies': "", # dependencies
    'rundependencies': "", # runtime dependencies
    'rundependenciesXT': "", # runtime dependencies + version
    'conflicts': "", # blockers
    'etpapi': "", # blockers
}

ETP_API = "1.0"

# variables
# should we import these into make.conf ?
pTree = "/var/lib/entropy/packages"
pTmpDir = pTree+"/tmp"
# fetch PORTAGE_BINHOST
f = open("/etc/make.conf","r")
makeConf = f.readlines()
pBinHost = ""
for line in makeConf:
    line = line.strip()
    if line.startswith("PORTAGE_BINHOST"):
	pBinHost = line.split('"')[1]
	break
if (pBinHost == ""):
    # force PORTAGE_BINHOST to our defaults
    pBinHost = "http://www.sabayonlinux.org/binhost/All/"
if not pBinHost.endswith("/"):
    pBinHost += "/"

import commands
if (commands.getoutput("q -V").find("portage-utils") != -1):
    pFindLibrary = "qfile -qC "
else:
    pFindLibrary = "equery belongs -n "

# Portage /var/db/<pkgcat>/<pkgname-pkgver>/*
# you never know if gentoo devs change these things
dbDESCRIPTION = "DESCRIPTION"
dbHOMEPAGE = "HOMEPAGE"
dbCHOST = "CHOST"
dbCATEGORY = "CATEGORY"
dbCFLAGS = "CFLAGS"
dbCXXFLAGS = "CXXFLAGS"
dbLICENSE = "LICENSE"
dbSRC_URI = "SRC_URI"
dbUSE = "USE"
dbIUSE = "IUSE"
dbDEPEND = "DEPEND"
dbRDEPEND = "RDEPEND"
dbPDEPEND = "PDEPEND"
dbNEEDED = "NEEDED"
dbOR = "|or|"
dbKEYWORDS = "KEYWORDS"