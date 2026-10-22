--[[ BetterMechanic Players for Lightroom Classic.

A window with two teams and the referees, every person a photo and a button: click to tag the photos selected
in Lightroom (keyword and IPTC "Person Shown"). The teams, people and pictures come from the BetterMechanic app,
which installs this plugin and keeps its data up to date.
]]

return {
	LrSdkVersion = 10.0,
	LrSdkMinimumVersion = 6.0,
	LrToolkitIdentifier = 'app.bettermechanic.players',
	LrPluginName = 'BetterMechanic Players',
	LrPluginInfoUrl = 'https://github.com/Rtx-9/bettermechanic',
	LrLibraryMenuItems = {
		{ title = 'BetterMechanic Players...', file = 'Players.lua' },
	},
	LrExportMenuItems = {
		{ title = 'BetterMechanic Players...', file = 'Players.lua' },
	},
	VERSION = { major = 0, minor = 10, revision = 0, build = 1 },
}
