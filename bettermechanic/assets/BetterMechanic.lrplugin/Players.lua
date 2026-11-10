--[[ The BetterMechanic Players window: two teams side by side and the referees. Click a person (the picture or
the name) to tag the photos selected in Lightroom; click again to take them off. People already on the selection
get a ✓. Lightroom can't change a window's layout once it's open, so hiding the referees or picking another size
closes the window and opens it again in the new layout. ]]

local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local Caption = require 'Caption'
local Data = require 'Data'
local Model = require 'Model'
local Tagging = require 'Tagging'

local bind = LrView.bind
local TILE_W, PIC = 104, 72

-- window sizes: tiles per row in a team's column and in the referees', and how tall the columns are
-- (medium fits a 1080p screen with the caption rows)
local SIZES = {
	{ value = 'small', title = 'Small', perRow = 3, refRow = 1, height = 300 },
	{ value = 'medium', title = 'Medium', perRow = 4, refRow = 2, height = 440 },
	{ value = 'large', title = 'Large', perRow = 5, refRow = 2, height = 600 },
}

local function sizeOf(value)
	for _, s in ipairs(SIZES) do
		if s.value == value then return s end
	end
	return SIZES[2]
end

-- one tile: picture and button. Lightroom only hides controls themselves (not rows or columns), so each has
-- its own visibility; a heading tile shows just its picture. Pictures can't be clicked, so an empty text the
-- size of the picture lies on top of it to take the click.
local function tile(f, k, onClick)
	local function click() onClick(k) end
	return f:column {
		width = TILE_W,
		spacing = 2,
		f:view {
			place = 'overlapping',
			place_horizontal = 0.5,
			f:picture { value = bind(k .. '_img'), visible = bind(k .. '_vis'), width = PIC, height = PIC },
			f:static_text { title = '', width = PIC, height = PIC, visible = bind(k .. '_btn'),
				tooltip = bind(k .. '_tip'), mouse_down = click },
		},
		f:push_button {
			title = bind(k .. '_title'), tooltip = bind(k .. '_tip'), visible = bind(k .. '_btn'),
			width = TILE_W - 4, size = 'small', action = click,
		},
	}
end

local function side(f, key, perRow, width, height, onClick)
	local col, row = { spacing = 6 }, nil
	for i = 1, Model.SLOTS[key] do
		if (i - 1) % perRow == 0 then
			row = { spacing = 4 }
			col[#col + 1] = row
		end
		row[#row + 1] = tile(f, key .. '_' .. i, onClick)
	end
	for j = 1, #col do
		col[j] = f:row(col[j])
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

	-- the teams last used here, else the ones chosen in the app, else the first team
	local first = teamItems(data, false)[1]
	local function pick(...)
		for _, id in ipairs({ ... }) do
			if id == '' or data.byId[id] then return id end
		end
	end
	props.teamA = pick(prefs.teamA or '-', data.defaults[1], first and first.value or '') or ''
	if props.teamA == '' and first then props.teamA = first.value end
	props.teamB = pick(prefs.teamB or '-', data.defaults[2], '')
	props.showRefs = data.referees ~= nil and prefs.showRefs ~= false
	props.size = sizeOf(prefs.size).value
	props.status = 'Select photos in Lightroom, then click a person.'
	props.template = prefs.template or ''
	props.writeCaption = prefs.writeCaption ~= false
	props.writeInfo = prefs.writeInfo ~= false
	local info = prefs.info
	local function infoText()
		if not info then return 'No game details yet: use From Game.' end
		return table.concat({ info.headline or '', info.location or '', info.city or '', info.country or '' }, '  ·  ')
	end
	props.infoText = infoText()

	local function redraw()
		Model.fillAll(props, shown, data, data.byId[props.teamA], data.byId[props.teamB], state.counts, state.n,
			state.game)
		if not props.showRefs then
			Model.fill(props, shown, 'r', {}, state.counts, state.n, data.blank)
		end
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
			local done, kept = Tagging.toggle(catalog, photos, entry, {
				template = props.writeCaption and props.template or nil,
				index = Caption.index(data, data.byId[props.teamA], data.byId[props.teamB]),
				info = props.writeInfo and info or nil,
			})
			local s = #photos == 1 and '' or 's'
			props.status = (done == 'added' and ('Tagged ' .. entry.name .. ' on ') or ('Removed ' .. entry.name .. ' from '))
				.. #photos .. ' photo' .. s
				.. (kept > 0 and ('. ' .. kept .. ' caption' .. (kept == 1 and '' or 's')
					.. ' left as you wrote ' .. (kept == 1 and 'it' or 'them') .. '.') or '')
			refresh(true)
		end)
	end

	-- a news caption and the game's details for the selected photo's game
	local function fromGame()
		LrTasks.startAsyncTask(function()
			local photos = Tagging.selection(catalog)
			local a, b = data.byId[props.teamA], data.byId[props.teamB]
			local game = Model.gameFor(data, Tagging.day(photos[1]), a and a.liiga, b and b.liiga)
			if not game then
				props.status = 'No game found: select a photo from the game, with one or both of its teams chosen above.'
				return
			end
			local template, details = Caption.fromGame(data, game)
			props.template = template
			prefs.template = template
			info = details
			prefs.info = details
			props.infoText = infoText()
			props.status = 'Caption and game details set for ' .. details.headline .. '.'
		end)
	end

	-- a new layout: close the window, and the loop at the end opens it again
	local window, reopen = nil, false
	local function relayout()
		if window and window.close then
			reopen = true
			window.close()
		else
			props.status = 'Close the window and open it again for the new layout.'
		end
	end

	-- observers run outside any task, and Lightroom only lets tasks read the catalog
	local function later(fn)
		return function() LrTasks.startAsyncTask(fn) end
	end
	props:addObserver('teamA', later(function() prefs.teamA = props.teamA; refresh(true) end))
	props:addObserver('teamB', later(function() prefs.teamB = props.teamB; refresh(true) end))
	props:addObserver('showRefs', later(function() prefs.showRefs = props.showRefs; redraw(); relayout() end))
	props:addObserver('size', later(function() prefs.size = props.size; relayout() end))
	props:addObserver('template', function() prefs.template = props.template end)
	props:addObserver('writeCaption', function() prefs.writeCaption = props.writeCaption end)
	props:addObserver('writeInfo', function() prefs.writeInfo = props.writeInfo end)

	local f = LrView.osFactory()
	local function build(size)
		local columns = { spacing = 10 }
		columns[1] = side(f, 'a', size.perRow, TILE_W * size.perRow + 40, size.height, onClick)
		columns[2] = side(f, 'b', size.perRow, TILE_W * size.perRow + 40, size.height, onClick)
		if props.showRefs then
			columns[3] = side(f, 'r', size.refRow, TILE_W * size.refRow + 40, size.height, onClick)
		end
		return f:column {
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
				f:popup_menu { items = SIZES, value = bind('size'), tooltip = 'How big the window is' },
			},
			f:row {
				spacing = 8,
				f:static_text { title = 'Caption', width = 52 },
				f:edit_field {
					value = bind('template'), width_in_chars = 50, fill_horizontal = 1, height_in_lines = 2,
					immediate = true,
					tooltip = 'Written into the caption of every photo you tag; {people} becomes the people on the photo, '
						.. 'e.g. "Kärppien Henrik Törnqvist (11) ja SaiPan Einar Emanuelsson (10)". A caption you wrote '
						.. 'yourself is kept: only the names in it change.',
				},
				f:push_button { title = 'From Game', action = fromGame,
					tooltip = 'A news caption and the headline, city, country and arena for the selected photo\'s game' },
			},
			f:row {
				spacing = 8,
				f:static_text { title = '', width = 52 },
				f:checkbox { title = 'Write caption', value = bind('writeCaption') },
				f:checkbox { title = 'Fill in headline, city, country, arena:', value = bind('writeInfo') },
				f:static_text { title = bind('infoText'), fill_horizontal = 1 },
			},
			f:row(columns),
			f:static_text { title = bind('status'), fill_horizontal = 1 },
		}
	end

	refresh(true)
	repeat
		reopen, window = false, nil
		local size = sizeOf(props.size)
		Data.windowOpen = true
		LrDialogs.presentFloatingDialog(_PLUGIN, {
			title = 'BetterMechanic Players',
			contents = build(size),
			-- one saved frame per layout: Lightroom doesn't shrink a window to smaller contents
			save_frame = 'BetterMechanicPlayersWindow_' .. size.value .. (props.showRefs and '' or '_norefs'),
			onShow = function(t) window = t end,
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
	until not reopen
end)
