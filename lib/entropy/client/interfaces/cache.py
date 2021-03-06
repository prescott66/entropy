# -*- coding: utf-8 -*-
"""

    @author: Fabio Erculiani <lxnay@sabayon.org>
    @contact: lxnay@sabayon.org
    @copyright: Fabio Erculiani
    @license: GPL-2

    B{Entropy Package Manager Client Cache Interface}.

"""
import os
import shutil
import hashlib

from entropy.i18n import _
from entropy.output import purple
from entropy.const import etpConst, const_setup_perms, \
    const_convert_to_unicode, const_convert_to_rawstring
from entropy.exceptions import RepositoryError
from entropy.cache import EntropyCacher
from entropy.db.exceptions import OperationalError, DatabaseError


class CacheMixin:

    def clear_cache(self):
        """
        Clear all the Entropy default cache directory. This function is
        fault tolerant and will never return any exception.
        """
        with self._cacher:
            # no data is written while holding self._cacher by the balls
            # drop all the buffers then remove on-disk data
            self._cacher.discard()
            # clear repositories live cache
            inst_repo = self.installed_repository()
            if inst_repo is not None:
                inst_repo.clearCache()
            with self._repodb_cache_mutex:
                for repo in self._repodb_cache.values():
                    repo.clearCache()
            cache_dir = self._cacher.current_directory()
            try:
                shutil.rmtree(cache_dir, True)
            except (shutil.Error, IOError, OSError):
                return
            try:
                os.makedirs(cache_dir, 0o775)
            except (IOError, OSError):
                return
            try:
                const_setup_perms(cache_dir, etpConst['entropygid'])
            except (IOError, OSError):
                return

    def _get_available_packages_hash(self):
        """
        Get available packages cache hash.
        """
        # client digest not needed, cache is kept updated
        c_hash = "%s|%s|%s" % (
            self._repositories_hash(),
            self._filter_available_repositories(),
            # needed when users do bogus things like editing config files
            # manually (branch setting)
            self._settings['repositories']['branch'])
        sha = hashlib.sha1()
        sha.update(const_convert_to_rawstring(repr(c_hash)))
        return sha.hexdigest()

    def _repositories_hash(self):
        """
        Return the checksum of available repositories, excluding package ones.
        """
        enabled_repos = self._filter_available_repositories()
        return self.__repositories_hash(enabled_repos)

    def __repositories_hash(self, repositories):
        sha = hashlib.sha1()
        sha.update(const_convert_to_rawstring("0"))
        for repo in repositories:
            try:
                dbconn = self.open_repository(repo)
            except (RepositoryError):
                continue # repo not available
            try:
                sha.update(const_convert_to_rawstring(repr(dbconn.mtime())))
            except (OperationalError, DatabaseError, OSError, IOError):
                txt = _("Repository") + " " + const_convert_to_unicode(repo) \
                    + " " + _("is corrupted") + ". " + \
                    _("Cannot calculate the checksum")
                self.output(
                    purple(txt),
                    importance = 1,
                    level = "warning"
                )
        return sha.hexdigest()

    def _all_repositories_hash(self):
        """
        Return the checksum of all the available repositories, including
        package repos.
        """
        return self.__repositories_hash(self._enabled_repos)

    def _filter_available_repositories(self, _enabled_repos = None):
        """
        Filter out package repositories from the list of available,
        enabled ones

        @keyword _enabled_repos: an alternative list of enabled repository
            identifiers
        @type _enabled_repos: list
        """
        if _enabled_repos is None:
            _enabled_repos = self._enabled_repos
        enabled_repos = [x for x in _enabled_repos if not \
            x.endswith(etpConst['packagesext_webinstall'])]
        enabled_repos = [x for x in enabled_repos if not \
            x.endswith(etpConst['packagesext'])]
        return enabled_repos
