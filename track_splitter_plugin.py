# -*- coding: utf-8 -*-
#
# Track Splitter Plugin for KiCad 8
#
# Author: Gemini
# Version: 1.0.0
#
# This plugin takes a single track and splits it into a bus of multiple parallel tracks.
# It provides a GUI to select the target net and configure the splitting parameters.
#
# WARNING: This plugin ONLY handles straight track segments. It does NOT process
#          vias or arc (curved) tracks, and it will break connectivity at
#          corners and T-junctions.
#
# ALWAYS BACK UP YOUR WORK BEFORE RUNNING.
#

import wx

# Helper class for the settings dialog
class SettingsDialog(wx.Dialog):
    def __init__(self, parent, title, board, preselected_net=None):
        super(SettingsDialog, self).__init__(parent, title=title, size=(350, 250))

        self.board = board
        self.panel = wx.Panel(self)
        self.vbox = wx.BoxSizer(wx.VERTICAL)

        # --- Net Selection ---
        nets = sorted([net.GetNetname() for net_code, net in self.board.GetNetsByNetcode().items() if net.GetNetname() != ""])
        
        sb_net = wx.StaticBox(self.panel, label='Target Net')
        sbs_net = wx.StaticBoxSizer(sb_net, wx.VERTICAL)
        self.net_choice = wx.Choice(self.panel, choices=nets)
        if preselected_net in nets:
            self.net_choice.SetSelection(nets.index(preselected_net))
        elif nets:
            self.net_choice.SetSelection(0)
        sbs_net.Add(self.net_choice, 0, wx.ALL | wx.EXPAND, 5)

        # --- Parameters Grid ---
        grid = wx.FlexGridSizer(3, 2, 9, 25)

        label_width = wx.StaticText(self.panel, label="Split Width (mm):")
        self.text_width = wx.TextCtrl(self.panel, value="1.4")
        
        label_sep = wx.StaticText(self.panel, label="Internal Separation (mm):")
        self.text_sep = wx.TextCtrl(self.panel, value="0.2")

        label_splits = wx.StaticText(self.panel, label="Number of Splits:")
        self.text_splits = wx.TextCtrl(self.panel, value="2")

        grid.AddMany([(label_width), (self.text_width, 1, wx.EXPAND),
                      (label_sep), (self.text_sep, 1, wx.EXPAND),
                      (label_splits), (self.text_splits, 1, wx.EXPAND)])
        grid.AddGrowableCol(1, 1)

        # --- Dialog Buttons ---
        button_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        # --- Layout ---
        self.vbox.Add(sbs_net, 0, wx.ALL | wx.EXPAND, 10)
        self.vbox.Add(grid, 1, wx.ALL | wx.EXPAND, 10)
        self.vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 10)
        
        self.panel.SetSizer(self.vbox)
        self.Centre()

    def get_settings(self):
        """Returns the settings entered by the user."""
        try:
            return {
                "net_name": self.net_choice.GetStringSelection(),
                "split_width": float(self.text_width.GetValue()),
                "internal_sep": float(self.text_sep.GetValue()),
                "num_splits": int(self.text_splits.GetValue()),
            }
        except (ValueError, TypeError):
            return None

# Main plugin class that KiCad will run
import pcbnew

class TrackSplitterPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Track Splitter"
        self.category = "Modify PCB"
        self.description = "Splits a single track into a bus of parallel tracks."
        self.show_toolbar_button = True
        self.icon_file_name = pcbnew.PCB_IMAGE_PATH + 'dialog-information.png' # Use a standard icon

    def Run(self):
        board = pcbnew.GetBoard()

        # Launch the settings dialog
        if not wx.App.IsMainLoopRunning():
            app = wx.App(False)

        windows = wx.GetTopLevelWindows()
        parent = wx.FindWindowByName("PcbEditorFrame") or (windows[0] if windows else None)

        selected_items = [x for x in board.GetTracks() if x.IsSelected()]
        preselected_net = None
        for item in selected_items:
            if isinstance(item, pcbnew.PCB_TRACK) and item.GetNetname():
                preselected_net = item.GetNetname()
                break

        dialog = SettingsDialog(parent, title="Track Splitter Settings", board=board, preselected_net=preselected_net)
        
        if dialog.ShowModal() == wx.ID_OK:
            settings = dialog.get_settings()
            if not settings:
                wx.MessageBox("Invalid input. Please check your numbers.", "Error", wx.OK | wx.ICON_ERROR)
                return
            
            # Execute the core logic
            self.split_tracks(board, settings)

        dialog.Destroy()

    def split_tracks(self, board, settings):
        """The core logic for finding, splitting, and replacing tracks."""
        
        original_net_name = settings["net_name"]
        num_splits = settings["num_splits"]

        if num_splits < 1:
            wx.MessageBox("Number of splits must be at least 1.", "Error", wx.OK | wx.ICON_ERROR)
            return

        # Convert to internal KiCad units (nanometers)
        split_width_iu = pcbnew.FromMM(settings["split_width"])
        internal_sep_iu = pcbnew.FromMM(settings["internal_sep"])
        group_width_iu = (split_width_iu * num_splits) + (internal_sep_iu * (num_splits - 1))

        # --- Stage 1: Find all tracks that need to be processed ---
        tracks_to_process = []
        for track in board.GetTracks():
            if track.GetNetname() == original_net_name:
                tracks_to_process.append(track)

        if not tracks_to_process:
            wx.MessageBox(f"No straight tracks found on net '{original_net_name}'.", "Info", wx.OK | wx.ICON_INFORMATION)
            return

        # --- Stage 2: Process each found track ---
        new_tracks_count = 0
        for track in tracks_to_process:
            start_pos = track.GetStart()
            end_pos = track.GetEnd()
            layer = track.GetLayer()
            net_code = track.GetNetCode()
            
            new_group = pcbnew.GROUP(board)
            board.Add(new_group)

            direction = pcbnew.VECTOR2I(end_pos.x - start_pos.x, end_pos.y - start_pos.y)
            length = (direction.x**2 + direction.y**2) ** 0.5
            unit_dx = direction.x / length
            unit_dy = direction.y / length
            shift_vec_x = -unit_dy
            shift_vec_y = unit_dx

            for i in range(num_splits):
                offset_iu = -group_width_iu / 2 + i * (split_width_iu + internal_sep_iu) + (split_width_iu / 2)
                shift_x = int(round(shift_vec_x * offset_iu))
                shift_y = int(round(shift_vec_y * offset_iu))
                shift = pcbnew.VECTOR2I(shift_x, shift_y)
                
                t = pcbnew.TRACK(board)
                t.SetStart(start_pos + shift)
                t.SetEnd(end_pos + shift)
                t.SetWidth(split_width_iu)
                t.SetNetCode(net_code)
                t.SetLayer(layer)
                
                board.Add(t)
                new_group.AddItem(t)
                new_tracks_count += 1
            
            board.Remove(track)
            
        # --- Finalization ---
        pcbnew.Refresh()
        summary_message = (
            f"Processed {len(tracks_to_process)} original track segments.\n"
            f"Created {new_tracks_count} new tracks for net '{original_net_name}'.\n\n"
            "Each new set of tracks has been grouped. You can select the entire group for easy modification.\n\n"
            "IMPORTANT: Please review corners, junctions, and via connections for continuity!"
        )
        wx.MessageBox(summary_message, "Track Splitter Finished", wx.OK | wx.ICON_INFORMATION)
