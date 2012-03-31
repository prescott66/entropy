# -*- coding: utf-8 -*-
"""
Copyright (C) 2012 Fabio Erculiani

Authors:
  Fabio Erculiani

This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; version 3.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
details.

You should have received a copy of the GNU General Public License along with
this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
"""

import os
import sys
from threading import Lock, Timer

sys.path.insert(0, "../lib")
sys.path.insert(1, "../client")
sys.path.insert(2, "./")
sys.path.insert(3, "/usr/lib/entropy/lib")
sys.path.insert(4, "/usr/lib/entropy/client")
sys.path.insert(5, "/usr/lib/entropy/rigo")
sys.path.insert(6, "/usr/lib/rigo")

from gi.repository import Gtk, Gdk, GLib

from rigo.paths import DATA_DIR
from rigo.enums import RigoViewStates, LocalActivityStates
from rigo.entropyapi import EntropyWebService, EntropyClient as Client
from rigo.ui.gtk3.widgets.apptreeview import AppTreeView
from rigo.ui.gtk3.widgets.notifications import NotificationBox
from rigo.ui.gtk3.controllers.applications import \
    ApplicationsViewController
from rigo.ui.gtk3.controllers.application import \
    ApplicationViewController

from rigo.ui.gtk3.controllers.notifications import \
    UpperNotificationViewController, BottomNotificationViewController
from rigo.ui.gtk3.controllers.work import \
    WorkViewController
from rigo.ui.gtk3.widgets.welcome import WelcomeBox
from rigo.ui.gtk3.models.appliststore import AppListStore
from rigo.ui.gtk3.utils import init_sc_css_provider, get_sc_icon_theme

from rigo.utils import escape_markup
from rigo.controllers.daemon import RigoServiceController

from RigoDaemon.enums import ActivityStates as DaemonActivityStates

from entropy.const import const_debug_write, dump_signal
from entropy.misc import TimeScheduled, ParallelTask, ReadersWritersSemaphore
from entropy.i18n import _

import entropy.tools


class Rigo(Gtk.Application):

    class RigoHandler(object):

        def __init__(self, rigo_app, rigo_service):
            self._app = rigo_app
            self._service = rigo_service

        def onDeleteWindow(self, window, event):
            # if UI is locked, do not allow to close Rigo
            if self._app.is_ui_locked() or \
                    self._service.local_activity() != LocalActivityStates.READY:
                rc = self._app._show_yesno_dialog(
                    None,
                    escape_markup(_("Hey hey hey!")),
                    escape_markup(_("Rigo is working, are you sure?")))
                if rc == Gtk.ResponseType.NO:
                    return True

            while True:
                try:
                    entropy.tools.kill_threads()
                    Gtk.main_quit((window, event))
                except KeyboardInterrupt:
                    continue
                break

    def __init__(self):
        self._current_state_lock = False
        self._current_state = RigoViewStates.STATIC_VIEW_STATE
        self._state_transactions = {
            RigoViewStates.BROWSER_VIEW_STATE: (
                self._enter_browser_state,
                self._exit_browser_state),
            RigoViewStates.STATIC_VIEW_STATE: (
                self._enter_static_state,
                self._exit_static_state),
            RigoViewStates.APPLICATION_VIEW_STATE: (
                self._enter_application_state,
                self._exit_application_state),
            RigoViewStates.WORK_VIEW_STATE: (
                self._enter_work_state,
                self._exit_work_state),
        }
        self._state_mutex = Lock()

        icons = get_sc_icon_theme(DATA_DIR)

        self._activity_rwsem = ReadersWritersSemaphore()
        self._entropy = Client()
        self._entropy_ws = EntropyWebService(self._entropy)
        self._service = RigoServiceController(
            self, self._activity_rwsem,
            self._entropy, self._entropy_ws)

        app_handler = Rigo.RigoHandler(self, self._service)

        self._builder = Gtk.Builder()
        self._builder.add_from_file(os.path.join(DATA_DIR, "ui/gtk3/rigo.ui"))
        self._builder.connect_signals(app_handler)
        self._window = self._builder.get_object("rigoWindow")
        self._window.set_name("rigo-view")
        self._apps_view = self._builder.get_object("appsViewVbox")
        self._scrolled_view = self._builder.get_object("appsViewScrolledWindow")
        self._app_view = self._builder.get_object("appViewScrollWin")
        self._app_view.set_name("rigo-view")
        self._app_view_port = self._builder.get_object("appViewVport")
        self._app_view_port.set_name("rigo-view")
        self._not_found_box = self._builder.get_object("appsViewNotFoundVbox")
        self._search_entry = self._builder.get_object("searchEntry")
        self._search_entry_completion = self._builder.get_object(
            "searchEntryCompletion")
        self._search_entry_store = self._builder.get_object(
            "searchEntryStore")
        self._static_view = self._builder.get_object("staticViewVbox")
        self._notification = self._builder.get_object("notificationBox")
        self._bottom_notification = \
            self._builder.get_object("bottomNotificationBox")
        self._work_view = self._builder.get_object("workViewVbox")
        self._work_view.set_name("rigo-view")

        self._app_view_c = ApplicationViewController(
            self._entropy, self._entropy_ws, self._service,
            self._builder)

        self._view = AppTreeView(
            self._entropy, self._service, self._app_view_c, icons,
            True, AppListStore.ICON_SIZE, store=None)
        self._scrolled_view.add(self._view)

        self._app_store = AppListStore(
            self._entropy, self._entropy_ws,
            self._service, self._view, icons)
        def _queue_draw(*args):
            self._view.queue_draw()
        self._app_store.connect("redraw-request", _queue_draw)

        self._app_view_c.set_store(self._app_store)
        self._app_view_c.connect("application-show",
            self._on_application_show)

        self._welcome_box = WelcomeBox()

        settings = Gtk.Settings.get_default()
        settings.set_property("gtk-error-bell", False)
        # wire up the css provider to reconfigure on theme-changes
        self._window.connect("style-updated",
                                 self._on_style_updated,
                                 init_sc_css_provider,
                                 settings,
                                 Gdk.Screen.get_default(),
                                 DATA_DIR)

        self._avc = ApplicationsViewController(
            self._activity_rwsem,
            self._entropy, self._entropy_ws, self._service,
            icons, self._not_found_box,
            self._search_entry, self._search_entry_completion,
            self._search_entry_store, self._app_store, self._view)

        self._avc.connect("view-cleared", self._on_view_cleared)
        self._avc.connect("view-filled", self._on_view_filled)
        self._avc.connect("view-want-change", self._on_view_change)

        self._nc = UpperNotificationViewController(
            self._activity_rwsem, self._entropy,
            self._entropy_ws, self._service,
            self._avc, self._notification)

        # Bottom NotificationBox controller.
        # Bottom notifications are only used for
        # providing Activity control to User during
        # the Activity itself.
        self._bottom_nc = BottomNotificationViewController(
            self._bottom_notification)
        self._service.set_bottom_notification_controller(
            self._bottom_nc)

        self._app_view_c.set_notification_controller(self._nc)
        self._app_view_c.set_applications_controller(self._avc)

        self._service.set_applications_controller(self._avc)
        self._service.set_application_controller(self._app_view_c)
        self._service.set_notification_controller(self._nc)

        self._service.connect("start-working", self._on_start_working)
        self._service.connect("repositories-updated",
                              self._on_repo_updated)
        self._service.connect("applications-managed",
                              self._on_applications_managed)

        self._work_view_c = WorkViewController(
            icons, self._service, self._work_view)
        self._service.set_work_controller(self._work_view_c)

        self._bottom_nc.connect("show-work-view", self._on_show_work_view)

    def is_ui_locked(self):
        """
        Return whether the UI is currently locked.
        """
        return self._current_state_lock

    def _thread_dumper(self):
        """
        If --dumper is in argv, a recurring thread dump
        function will be spawned every 30 seconds.
        """
        dumper_enable = "--dumper" in sys.argv
        if dumper_enable:
            task = None

            def _dumper():
                def _dump():
                    task.kill()
                    dump_signal(None, None)
                timer = Timer(10.0, _dump)
                timer.name = "MainThreadHearthbeatCheck"
                timer.daemon = True
                timer.start()
                GLib.idle_add(timer.cancel)

            task = TimeScheduled(5.0, _dumper)
            task.name = "ThreadDumper"
            task.daemon = True
            task.start()

    def _on_start_working(self, widget, state, lock):
        """
        Emitted by RigoServiceController when we're asked to
        switch to the Work View and, if lock = True, lock UI.
        """
        if lock:
            self._search_entry.set_sensitive(False)
        if state is not None:
            self._change_view_state(state, lock=lock)

    def _on_show_work_view(self, widget):
        """
        We've been explicitly asked to switch to WORK_VIEW_STATE
        """
        self._change_view_state(RigoViewStates.WORK_VIEW_STATE,
                                _ignore_lock=True)

    def _on_repo_updated(self, widget, result, message):
        """
        Emitted by RigoServiceController telling us that
        repositories have been updated.
        """
        with self._state_mutex:
            self._current_state_lock = False
        self._search_entry.set_sensitive(True)
        if result != 0:
            msg = "<b>%s</b>: %s" % (
                _("Repositories update error"),
                message,)
            message_type = Gtk.MessageType.ERROR
        else:
            msg = _("Repositories updated <b>successfully</b>!")
            message_type = Gtk.MessageType.INFO

        box = NotificationBox(
            msg, message_type=message_type,
            context_id=RigoServiceController.NOTIFICATION_CONTEXT_ID)
        box.add_destroy_button(_("Ok, thanks"))
        self._nc.append(box)

    def _on_applications_managed(self, widget, success, local_activity):
        """
        Emitted by RigoServiceController telling us that
        enqueue application actions have been completed.
        """
        msg = "N/A"
        if not success:
            if local_activity == LocalActivityStates.MANAGING_APPLICATIONS:
                msg = "<b>%s</b>: %s" % (
                    _("Application Management Error"),
                    _("please check the management log"),)
            elif local_activity == LocalActivityStates.UPGRADING_SYSTEM:
                msg = "<b>%s</b>: %s" % (
                    _("System Upgrade Error"),
                    _("please check the upgrade log"),)
            message_type = Gtk.MessageType.ERROR
        else:
            if local_activity == LocalActivityStates.MANAGING_APPLICATIONS:
                msg = _("Applications managed <b>successfully</b>!")
            elif local_activity == LocalActivityStates.UPGRADING_SYSTEM:
                msg = _("System Upgraded <b>successfully</b>!")
            message_type = Gtk.MessageType.INFO

        box = NotificationBox(
            msg, message_type=message_type,
            context_id=RigoServiceController.NOTIFICATION_CONTEXT_ID)
        box.add_destroy_button(_("Ok, thanks"))
        box.add_button(_("Show me"), self._on_show_work_view)
        self._nc.append(box)
        self._work_view_c.deactivate_app_box()

    def _on_view_cleared(self, *args):
        self._change_view_state(RigoViewStates.STATIC_VIEW_STATE)

    def _on_view_filled(self, *args):
        self._change_view_state(RigoViewStates.BROWSER_VIEW_STATE)

    def _on_view_change(self, widget, state):
        self._change_view_state(state)

    def _on_application_show(self, *args):
        self._change_view_state(RigoViewStates.APPLICATION_VIEW_STATE)

    def _exit_browser_state(self):
        """
        Action triggered when UI exits the Application Browser
        state (or mode).
        """
        self._apps_view.hide()

    def _enter_browser_state(self):
        """
        Action triggered when UI exits the Application Browser
        state (or mode).
        """
        self._apps_view.show()

    def _exit_static_state(self):
        """
        Action triggered when UI exits the Static Browser
        state (or mode). AKA the Welcome Box.
        """
        self._static_view.hide()
        # release all the childrens of static_view
        for child in self._static_view.get_children():
            self._static_view.remove(child)

    def _enter_static_state(self):
        """
        Action triggered when UI exits the Static Browser
        state (or mode). AKA the Welcome Box.
        """
        # keep the current widget if any, or add the
        # welcome widget
        if not self._static_view.get_children():
            self._welcome_box.show()
            self._static_view.pack_start(self._welcome_box,
                                         True, True, 10)
        self._static_view.show()

    def _enter_application_state(self):
        """
        Action triggered when UI enters the Package Information
        state (or mode). Showing application information.
        """
        # change search_entry first icon to emphasize the
        # back action
        self._search_entry.set_icon_from_stock(
            Gtk.EntryIconPosition.PRIMARY,
            "gtk-go-back")
        self._app_view.show()

    def _exit_application_state(self):
        """
        Action triggered when UI exits the Package Information
        state (or mode). Hiding back application information.
        """
        self._search_entry.set_icon_from_stock(
            Gtk.EntryIconPosition.PRIMARY, "gtk-find")
        self._app_view.hide()
        self._app_view_c.hide()

    def _enter_work_state(self):
        """
        Action triggered when UI enters the Work View state (or mode).
        Either for Updating Repositories or Installing new Apps.
        """
        self._work_view.show()

    def _exit_work_state(self):
        """
        Action triggered when UI exits the Work View state (or mode).
        """
        self._work_view.hide()

    def _change_view_state(self, state, lock=False, _ignore_lock=False):
        """
        Change Rigo Application UI state.
        You can pass a custom widget that will be shown in case
        of static view state.
        """
        with self._state_mutex:
            if self._current_state_lock and not _ignore_lock:
                const_debug_write(
                    __name__,
                    "cannot change view state, UI locked")
                return False
            txc = self._state_transactions.get(state)
            if txc is None:
                raise AttributeError("wrong view state")
            enter_st, exit_st = txc

            current_enter_st, current_exit_st = self._state_transactions.get(
                self._current_state)
            # exit from current state
            current_exit_st()
            # enter the new state
            enter_st()
            self._current_state = state
            if lock:
                self._current_state_lock = True

            return True

    def _change_view_state_safe(self, state):
        """
        Thread-safe version of change_view_state().
        """
        def _do_change():
            return self._change_view_state(state)
        GLib.idle_add(_do_change)

    def _on_style_updated(self, widget, init_css_callback, *args):
        """
        Gtk Style callback, nothing to see here.
        """
        init_css_callback(widget, *args)

    def _show_ok_dialog(self, parent, title, message):
        """
        Show ugly OK dialog window.
        """
        dlg = Gtk.MessageDialog(parent=parent,
                            type=Gtk.MessageType.INFO,
                            buttons=Gtk.ButtonsType.OK)
        dlg.set_markup(message)
        dlg.set_title(title)
        dlg.run()
        dlg.destroy()

    def _show_yesno_dialog(self, parent, title, message):
        """
        Show ugly Yes/No dialog window.
        """
        dlg = Gtk.MessageDialog(parent=parent,
                            type=Gtk.MessageType.INFO,
                            buttons=Gtk.ButtonsType.YES_NO)
        dlg.set_markup(message)
        dlg.set_title(title)
        rc = dlg.run()
        dlg.destroy()
        return rc

    def _permissions_setup(self):
        """
        Check execution privileges and spawn the Rigo UI.
        """
        if not entropy.tools.is_user_in_entropy_group():
            # otherwise the lock handling would potentially
            # fail.
            self._show_ok_dialog(
                None,
                escape_markup(_("Not authorized")),
                escape_markup(_("You are not authorized to run Rigo")))
            entropy.tools.kill_threads()
            Gtk.main_quit()
            return

        if not self._service.service_available():
            self._show_ok_dialog(
                None,
                escape_markup(_("Rigo")),
                escape_markup(_("RigoDaemon service is not available")))
            entropy.tools.kill_threads()
            Gtk.main_quit()
            return

        supported_apis = self._service.supported_apis()
        daemon_api = self._service.api()
        if daemon_api not in supported_apis:
            self._show_ok_dialog(
                None,
                escape_markup(_("Rigo")),
                escape_markup(
                    _("API mismatch, please update Rigo and RigoDaemon")))
            entropy.tools.kill_threads()
            Gtk.main_quit()
            return

        acquired = not self._entropy.wait_resources(
            max_lock_count=1,
            shared=True)
        is_exclusive = False
        if not acquired:
            # check whether RigoDaemon is running in excluive mode
            # and ignore non-atomicity here (failing with error
            # is acceptable)
            if not self._service.exclusive():
                self._show_ok_dialog(
                    None,
                    escape_markup(_("Rigo")),
                    escape_markup(_("Another Application Manager is active")))
                entropy.tools.kill_threads()
                Gtk.main_quit()
                return
            is_exclusive = True
            # otherwise we can go ahead and handle our state later

        # check RigoDaemon, don't worry about races between Rigo Clients
        # it is fine to have multiple Rigo Clients connected. Mutual
        # exclusion is handled via Entropy Resources Lock (which is a file
        # based rwsem).
        activity = self._service.activity()
        if activity != DaemonActivityStates.AVAILABLE:
            msg = ""
            show_dialog = True

            if activity == DaemonActivityStates.NOT_AVAILABLE:
                msg = _("Background Service is currently not available")

            elif activity == DaemonActivityStates.UPDATING_REPOSITORIES:
                show_dialog = False
                task = ParallelTask(
                    self._service._update_repositories,
                    [], False, master=False)
                task.daemon = True
                task.name = "UpdateRepositoriesUnlocked"
                task.start()

            elif activity == DaemonActivityStates.MANAGING_APPLICATIONS:
                show_dialog = False
                task = ParallelTask(
                    self._service._application_request,
                    None, None, master=False)
                task.daemon = True
                task.name = "ApplicationRequestUnlocked"
                task.start()

            elif activity == DaemonActivityStates.UPGRADING_SYSTEM:
                show_dialog = False
                task = ParallelTask(
                    self._service._upgrade_system,
                    False, master=False)
                task.daemon = True
                task.name = "UpgradeSystemUnlocked"
                task.start()

            elif activity == DaemonActivityStates.INTERNAL_ROUTINES:
                msg = _("Background Service is currently busy")
            else:
                msg = _("Background Service is incompatible with Rigo")

            if show_dialog:
                self._show_ok_dialog(
                    None,
                    escape_markup(_("Rigo")),
                    escape_markup(msg))
                entropy.tools.kill_threads()
                Gtk.main_quit()
                return

        elif is_exclusive:
            msg = _("Background Service is currently unavailable")
            # no lock acquired, cannot continue the initialization
            self._show_ok_dialog(
                None,
                escape_markup(_("Rigo")),
                escape_markup(msg))
            entropy.tools.kill_threads()
            Gtk.main_quit()
            return

        self._thread_dumper()
        self._app_view_c.setup()
        self._avc.setup()
        self._nc.setup()
        self._work_view_c.setup()
        self._service.setup(acquired)
        self._window.show()

    def run(self):
        """
        Run Rigo ;-)
        """
        self._welcome_box.render()
        self._change_view_state(self._current_state)
        GLib.idle_add(self._permissions_setup)

        GLib.threads_init()
        Gdk.threads_enter()
        Gtk.main()
        Gdk.threads_leave()
        entropy.tools.kill_threads()

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = Rigo()
    app.run()
