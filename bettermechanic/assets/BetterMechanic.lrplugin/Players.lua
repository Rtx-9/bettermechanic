--[[ The BetterMechanic Players window: two teams side by side and the referees. Click a person to tag the
photos selected in Lightroom; click again to take them off. People already on the selection get a ✓. ]]

local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local Data = require 'Data'
local Model = require 'Model'
local Tagging = require 'Tagging'

local bind = LrView.bind
local TILE_W, PIC = 104, 72

local function tile(f, key, i, onClick)
	local k = key .. '_' .. i
	return f:column {
		visible = bind(k .. '_vis'),
		width = TILE_W,
		spacing = 2,
		place_horizontal = 0.5,
		f:picture { value = bind(k .. '_img'), width = PIC, height = PIC, place_horizontal = 0.5 },
		f:push_button {
			title = bind(k .. '_title'), tooltip = bind(k .. '_tip'), width = TILE_W - 4, size = 'small',
			action = function() onClick(k) end,
		},
	}
end

local function group(f, g, perRow, onClick)
	local col = { spacing = 6 }
	col[#col + 1] = f:static_text { title = bind(g.key .. '_head'), visible = bind(g.key .. '_any'),
		font = '<system/small/bold>' }
	local row
	for i = 1, g.slots do
		if (i - 1) % perRow == 0 then
			row = { spacing = 4, visible = bind(g.key .. '_row_' .. (math.floor((i - 1) / perRow) + 1)) }
			col[#col + 1] = row
		end
		row[#row + 1] = tile(f, g.key, i, onClick)
	end
	for j = 2, #col do
		col[j] = f:row(col[j])
	end
	return f:column(col)
end

local function side(f, groups, perRow, width, height, onClick)
	local col = { spacing = 12 }
	for _, g in ipairs(groups) do
		col[#col + 1] = group(f, g, perRow, onClick)
	end
	return f:scrolled_view { width = width, height = height, horizontal_scroller = false, f:column(col) }
end

local function teamItems(data, withNone)
	local items = {}
	if withNone then items[1] = { title = 'No second team', value = '' } end
	for _, t in ipairs(data.teams) do
		if t.liiga ~= 'referees' then items[#items + 1] = { title = t.name, value = t.id } end
	end
	return items
end

LrFunctionContext.postAsyncTaskWithContext('BetterMechanicPlayers', function(context)
	LrDialogs.attachErrorDialogToFunctionContext(context)
	local data, missing = Data.load()
	if not data then
		LrDialogs.message('BetterMechanic Players',
			'No teams yet. Open BetterMechanic and choose Settings > Install Lightroom Plugin; it writes them to\n'
			.. missing, 'info')
		return
	end
	if Data.windowOpen then
		LrDialogs.message('BetterMechanic Players', 'The Players window is already open.', 'info')
		return
	end

	local catalog = LrApplication.activeCatalog()
	local prefs = LrPrefs.prefsForPlugin()
	local props = LrBinding.makePropertyTable(context)
	local shown, state = {}, { counts = {}, n = 0, game = nil, selKey = nil, sinceFull = 0 }

	local first = teamItems(data, false)[1]
	props.teamA = data.byId[prefs.teamA or ''] and prefs.teamA or (first and first.value or '')
	props.teamB = (prefs.teamB == '' or data.byId[prefs.teamB or '']) and prefs.teamB or ''
	props.showRefs = data.referees ~= nil and prefs.showRefs ~= false
	props.status = 'Select photos in Lightroom, then click a person.'

	local function redraw()
		Model.fillAll(props, shown, data, data.byId[props.teamA], data.byId[props.teamB], state.counts, state.n,
			state.game)
	end

	-- selection, its keywords and its game; redraw only when something changed
	local function refresh(force)
		local photos = Tagging.selection(catalog)
		local key = #photos .. ':' .. (photos[1] and photos[1].localIdentifier or '') .. ':'
			.. (photos[#photos] and photos[#photos].localIdentifier or '')
		state.sinceFull = state.sinceFull + 1
		if not force and key == state.selKey and state.sinceFull < 6 then return end
		state.selKey, state.sinceFull = key, 0
		local counts, n = Tagging.counts(photos, 300)
		local a, b = data.byId[props.teamA], data.byId[props.teamB]
		local game = Model.gameFor(data, Tagging.day(photos[1]), a and a.liiga, b and b.liiga)
		state.counts, state.n, state.game = counts, n, game
		redraw()
	end

	local function onClick(k)
		local entry = shown[k]
		if not entry then return end
		LrTasks.startAsyncTask(function()
			local photos = Tagging.selection(catalog)
			if #photos == 0 then
				props.status = 'Select one or more photos first.'
				return
			end
			local done = Tagging.toggle(catalog, photos, entry)
			local s = #photos == 1 and '' or 's'
			props.status = (done == 'added' and ('Tagged ' .. entry.name .. ' on ') or ('Removed ' .. entry.name .. ' from '))
				.. #photos .. ' photo' .. s
			refresh(true)
		end)
	end

	props:addObserver('teamA', function() prefs.teamA = props.teamA; refresh(true) end)
	props:addObserver('teamB', function() prefs.teamB = props.teamB; refresh(true) end)
	props:addObserver('showRefs', function() prefs.showRefs = props.showRefs end)

	local f = LrView.osFactory()
	local contents = f:column {
		bind_to_object = props,
		spacing = 8,
		f:row {
			spacing = 8,
			f:popup_menu { items = teamItems(data, false), value = bind('teamA'), width = 200 },
			f:push_button { title = '⇄', tooltip = 'Swap the teams', action = function()
				if props.teamB ~= '' then props.teamA, props.teamB = props.teamB, props.teamA end
			end },
			f:popup_menu { items = teamItems(data, true), value = bind('teamB'), width = 200 },
			f:checkbox { title = 'Referees', value = bind('showRefs'), enabled = data.referees ~= nil },
		},
		f:row {
			spacing = 10,
			side(f, Model.GROUPS.a, Model.PER_ROW, TILE_W * Model.PER_ROW + 40, 560, onClick),
			side(f, Model.GROUPS.b, Model.PER_ROW, TILE_W * Model.PER_ROW + 40, 560, onClick),
			f:view {
				visible = bind('showRefs'),
				side(f, Model.GROUPS.r, Model.REF_ROW, TILE_W * Model.REF_ROW + 40, 560, onClick),
			},
		},
		f:static_text { title = bind('status'), fill_horizontal = 1 },
	}

	refresh(true)
	Data.windowOpen = true
	LrDialogs.presentFloatingDialog(_PLUGIN, {
		title = 'BetterMechanic Players',
		contents = contents,
		save_frame = 'BetterMechanicPlayersWindow',
		windowWillClose = function() Data.windowOpen = false end,
		selectionChangeObserver = function()
			LrTasks.startAsyncTask(function() refresh(true) end)
		end,
	})
	-- keep the marks current (and this context, which owns the property table, alive) while it's open
	while Data.windowOpen do
		LrTasks.sleep(0.5)
		refresh(false)
	end
end)
