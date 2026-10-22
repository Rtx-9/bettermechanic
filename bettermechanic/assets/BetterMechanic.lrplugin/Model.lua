--[[ What the window shows: which person sits in which tile, the referees of the photo's game, the marks for
people already on the selected photos. Plain Lua with no Lightroom calls, so it can be tested on its own.

Lightroom windows can't add or remove controls once open, and hidden controls keep their space, so each side is
one run of tiles filled from the start: players, a "Staff" heading tile, staff (the referees: this game's,
referees, linesmen). The unused tiles at the end stay hidden. The property table says what each tile shows:
<side>_<i>_vis (picture shown), _img, _btn (button shown), _title, _tip.
]]

local Model = {}

Model.PER_ROW = 4
Model.REF_ROW = 2
Model.SLOTS = { a = 84, b = 84, r = 72 }

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

local function append(seq, list)
	for _, e in ipairs(list) do seq[#seq + 1] = e end
end

local function heading(seq, data, name, list)
	if #list > 0 then
		seq[#seq + 1] = { heading = name, image = data.headings[name] }
		append(seq, list)
	end
end

-- a team's tiles: players, then a Staff heading and the staff
function Model.teamSequence(data, team)
	local players, staff = {}, {}
	for _, e in ipairs(team and team.people or {}) do
		if e.role == '' then players[#players + 1] = e else staff[#staff + 1] = e end
	end
	local seq = {}
	append(seq, players)
	if #players > 0 then
		heading(seq, data, 'staff', staff)
	else
		append(seq, staff)
	end
	return seq
end

-- the referees' tiles: this game's officials first (as the game lists them), then referees, then linesmen
function Model.refSequence(data, game)
	local here, first, refs, lines = {}, {}, {}, {}
	if game then
		for i, name in ipairs(game.refs) do here[name] = i end
	end
	for _, e in ipairs(data.referees and data.referees.people or {}) do
		if here[e.name] then
			first[#first + 1] = e
		elseif e.role == 'Linesman' then
			lines[#lines + 1] = e
		else
			refs[#refs + 1] = e
		end
	end
	table.sort(first, function(x, y) return here[x.name] < here[y.name] end)
	local seq = {}
	heading(seq, data, 'game', first)
	heading(seq, data, 'referees', refs)
	heading(seq, data, 'linesmen', lines)
	return seq
end

-- put a sequence into the tiles of one side; shown[<side>_<i>] = entry for the click handler
function Model.fill(props, shown, side, seq, counts, n, blank)
	for i = 1, Model.SLOTS[side] do
		local k = side .. '_' .. i
		local e = seq[i]
		shown[k] = e and not e.heading and e or nil
		props[k .. '_vis'] = e ~= nil
		props[k .. '_img'] = e and e.image or blank
		props[k .. '_btn'] = e ~= nil and not e.heading
		props[k .. '_title'] = (e and not e.heading) and (Model.mark(e, counts, n) .. Model.label(e)) or ''
		props[k .. '_tip'] = (e and not e.heading) and Model.tooltip(e) or ''
	end
end

-- everything in the window for these teams, this selection and this game
function Model.fillAll(props, shown, data, teamA, teamB, counts, n, game)
	Model.fill(props, shown, 'a', Model.teamSequence(data, teamA), counts, n, data.blank)
	Model.fill(props, shown, 'b', Model.teamSequence(data, teamB), counts, n, data.blank)
	Model.fill(props, shown, 'r', Model.refSequence(data, game), counts, n, data.blank)
end

return Model
