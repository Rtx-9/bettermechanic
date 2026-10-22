--[[ What the window shows: which person sits in which tile, the referees of the photo's game, the marks for
people already on the selected photos. Plain Lua with no Lightroom calls, so it can be tested on its own.

Lightroom windows can't add or remove controls once open, so every group has a fixed number of tiles and the
property table says what each one shows: <group>_<i>_vis / _img / _title / _tip, plus <group>_head and
<group>_any for the group heading and <group>_row_<r> for each row of tiles.
]]

local Model = {}

Model.PER_ROW = 4
Model.REF_ROW = 2
Model.GROUPS = {
	a = { { key = 'ap', title = 'Players', slots = 48 }, { key = 'as', title = 'Staff', slots = 32 } },
	b = { { key = 'bp', title = 'Players', slots = 48 }, { key = 'bs', title = 'Staff', slots = 32 } },
	r = { { key = 'rg', title = 'This game', slots = 6 }, { key = 'rr', title = 'Referees', slots = 40 },
		{ key = 'rl', title = 'Linesmen', slots = 40 } },
}

function Model.lastName(name)
	return name:match('(%S+)%s*$') or name
end

function Model.label(entry)
	local last = Model.lastName(entry.name)
	if entry.number ~= '' then
		return '#' .. entry.number .. ' ' .. last
	end
	return last
end

function Model.tooltip(entry)
	local bits = { entry.name }
	if entry.number ~= '' then bits[#bits + 1] = '#' .. entry.number end
	if entry.role ~= '' then bits[#bits + 1] = entry.role end
	return table.concat(bits, '  ·  ')
end

-- ✓ on everyone selected, a dot when only some of them
function Model.mark(entry, counts, n)
	local c = counts[entry.name] or 0
	if n > 0 and c == n then
		return '✓ '
	elseif c > 0 then
		return '• '
	end
	return ''
end

function Model.teamGroups(team)
	local players, staff = {}, {}
	for _, e in ipairs(team and team.people or {}) do
		if e.role == '' then players[#players + 1] = e else staff[#staff + 1] = e end
	end
	return players, staff
end

-- the game on `day` between the teams shown (either may be missing), or nil
function Model.gameFor(data, day, liigaA, liigaB)
	if not day or day == '' then return nil end
	local want = {}
	for _, id in ipairs({ liigaA or '', liigaB or '' }) do
		if id ~= '' and id ~= 'referees' then want[#want + 1] = id end
	end
	if #want == 0 then return nil end
	for _, g in ipairs(data.games) do
		if g.date == day then
			local ok = true
			for _, id in ipairs(want) do
				if g.teams[1] ~= id and g.teams[2] ~= id then ok = false end
			end
			if ok then return g end
		end
	end
	return nil
end

function Model.refGroups(team, game)
	local here, first, refs, lines = {}, {}, {}, {}
	if game then
		for i, name in ipairs(game.refs) do here[name] = i end
	end
	for _, e in ipairs(team and team.people or {}) do
		if here[e.name] then
			first[#first + 1] = e
		elseif e.role == 'Linesman' then
			lines[#lines + 1] = e
		else
			refs[#refs + 1] = e
		end
	end
	table.sort(first, function(x, y) return here[x.name] < here[y.name] end)   -- as the game lists them
	return first, refs, lines
end

-- put `entries` into the tiles of group `g`; shown[<group>_<i>] = entry for the click handler
function Model.fill(props, shown, g, entries, perRow, counts, n, blank)
	local count = math.min(#entries, g.slots)
	for i = 1, g.slots do
		local k = g.key .. '_' .. i
		local e = entries[i]
		shown[k] = e
		if e then
			props[k .. '_vis'] = true
			props[k .. '_img'] = e.image or blank
			props[k .. '_title'] = Model.mark(e, counts, n) .. Model.label(e)
			props[k .. '_tip'] = Model.tooltip(e)
		else
			props[k .. '_vis'] = false
			props[k .. '_img'] = blank
			props[k .. '_title'] = ''
			props[k .. '_tip'] = ''
		end
	end
	for r = 1, math.ceil(g.slots / perRow) do
		props[g.key .. '_row_' .. r] = (r - 1) * perRow < count
	end
	props[g.key .. '_any'] = count > 0
	props[g.key .. '_head'] = string.upper(g.title) .. '   ' .. count
end

-- everything in the window for these teams, this selection and this game
function Model.fillAll(props, shown, data, teamA, teamB, counts, n, game)
	local groups = Model.GROUPS
	local p, s = Model.teamGroups(teamA)
	Model.fill(props, shown, groups.a[1], p, Model.PER_ROW, counts, n, data.blank)
	Model.fill(props, shown, groups.a[2], s, Model.PER_ROW, counts, n, data.blank)
	p, s = Model.teamGroups(teamB)
	Model.fill(props, shown, groups.b[1], p, Model.PER_ROW, counts, n, data.blank)
	Model.fill(props, shown, groups.b[2], s, Model.PER_ROW, counts, n, data.blank)
	local first, refs, lines = Model.refGroups(data.referees, game)
	Model.fill(props, shown, groups.r[1], first, Model.REF_ROW, counts, n, data.blank)
	Model.fill(props, shown, groups.r[2], refs, Model.REF_ROW, counts, n, data.blank)
	Model.fill(props, shown, groups.r[3], lines, Model.REF_ROW, counts, n, data.blank)
end

return Model
