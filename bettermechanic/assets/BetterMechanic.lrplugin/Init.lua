--[[ Runs when Lightroom loads the plugin: watch for photos the BetterMechanic app sends, until the plugin is
reloaded, disabled or Lightroom quits (Shutdown.lua). ]]

local LrApplication = import 'LrApplication'
local LrLogger = import 'LrLogger'
local LrTasks = import 'LrTasks'

local Inbox = require 'Inbox'

local log = LrLogger('BetterMechanic')
log:enable('logfile')                  -- Documents\LrClassicLogs\BetterMechanic.log

local me = {}
Inbox.watcher = me
LrTasks.startAsyncTask(function()
	log:info('watching ' .. Inbox.folder())
	local last
	while Inbox.watcher == me and _PLUGIN.enabled ~= false do
		local ok, err = LrTasks.pcall(Inbox.process, LrApplication.activeCatalog())
		if not ok and tostring(err) ~= last then
			log:error(tostring(err))
		end
		last = not ok and tostring(err) or nil
		LrTasks.sleep(1)
	end
	log:info('stopped')
end)
