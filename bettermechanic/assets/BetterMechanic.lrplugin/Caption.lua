--[[ News captions in Finnish, the way newsrooms and agencies expect them:

  "Kärppien Henrik Törnqvist (11) ja SaiPan Einar Emanuelsson (10) Liigan ottelussa Kärpät–SaiPa Oulussa
   20. lokakuuta 2026."

You set a caption with {people} in it before editing (or let "From game" write one for the photo's game); every
photo you tag then gets it, with {people} filled in from the people on that photo. Plain Lua, no Lightroom calls.
]]

local Caption = {}

Caption.MONTHS = { 'tammikuuta', 'helmikuuta', 'maaliskuuta', 'huhtikuuta', 'toukokuuta', 'kesäkuuta',
	'heinäkuuta', 'elokuuta', 'syyskuuta', 'lokakuuta', 'marraskuuta', 'joulukuuta' }
Caption.ROLES = { Referee = 'päätuomari', Linesman = 'linjatuomari' }

-- '2026-10-20' -> '20. lokakuuta 2026'
function Caption.longDate(day)
	local y, m, d = (day or ''):match('^(%d+)-(%d+)-(%d+)$')
	if not y then return '' end
	return tonumber(d) .. '. ' .. Caption.MONTHS[tonumber(m)] .. ' ' .. y
end

local function lowerFirst(s)
	return (s:gsub('^%u', string.lower))
end

local function upperFirst(s)
	return (s:gsub('^%l', string.upper))
end

-- 'A', 'A ja B', 'A, B ja C'
function Caption.join(list)
	if #list <= 1 then return list[1] or '' end
	return table.concat(list, ', ', 1, #list - 1) .. ' ja ' .. list[#list]
end

-- one person as written in a caption: "Henrik Törnqvist (11)", "päävalmentaja Petri Karjalainen"
function Caption.person(entry)
	if not entry then return '' end
	local text = entry.name
	if entry.role ~= '' then
		text = lowerFirst(Caption.ROLES[entry.role] or entry.role) .. ' ' .. text
	elseif entry.number ~= '' then
		text = text .. ' (' .. entry.number .. ')'
	end
	return text
end

--[[ The people on a photo, in the order they were tagged, grouped by team:
     "Kärppien Henrik Törnqvist (11) ja Eetu Koivistoinen (31) sekä SaiPan Einar Emanuelsson (10)".
     index: name -> entry; names it doesn't know are written as they are. ]]
function Caption.people(names, index)
	local groups, byTeam = {}, {}
	for _, name in ipairs(names) do
		local e = index[name]
		local key = e and e.team and e.team.genitive ~= '' and e.team.id or ('_' .. name)
		local g = byTeam[key]
		if not g then
			g = { prefix = e and e.team and e.team.genitive or '', items = {} }
			byTeam[key] = g
			groups[#groups + 1] = g
		end
		g.items[#g.items + 1] = e and Caption.person(e) or name
	end
	local parts = {}
	for _, g in ipairs(groups) do
		local text = Caption.join(g.items)
		parts[#parts + 1] = g.prefix ~= '' and (g.prefix .. ' ' .. text) or text
	end
	if #parts <= 2 then return table.concat(parts, ' ja ') end
	return table.concat(parts, ', ', 1, #parts - 1) .. ' sekä ' .. parts[#parts]
end

-- the template with {people} filled in, tidied (no stray spaces, capital first letter)
function Caption.render(template, peopleText)
	local s = template:gsub('{people}', function() return peopleText end)
	s = s:gsub('%s+([%.,;:!?])', '%1'):gsub('%s%s+', ' '):gsub('^%s+', ''):gsub('%s+$', '')
	return upperFirst(s)
end

--[[ The caption a photo should get when its people change from oldText to newText, or nil to leave it:
     - empty, or exactly what the template made before: written anew from the template
     - your own wording that has the names in it: just the names are swapped
     - anything else is yours and stays as it is ]]
function Caption.update(current, template, oldText, newText)
	current = current or ''
	if not template or template == '' then return nil end
	if current == '' or current == Caption.render(template, oldText) then
		if newText == '' then return '' end
		return Caption.render(template, newText)
	end
	if oldText ~= '' then
		local i, j = current:find(oldText, 1, true)
		if i then
			return upperFirst((current:sub(1, i - 1) .. newText .. current:sub(j + 1)):gsub('%s%s+', ' '):gsub('^%s+', ''))
		end
	end
	return nil
end

--[[ A caption and the game's details for news photos, from the game a photo is from:
     template "{people} Liigan ottelussa Kärpät–SaiPa Oulussa 20. lokakuuta 2026." and
     info { headline = 'Kärpät–SaiPa', city = 'Oulu', country = 'Finland', isoCountryCode = 'FI',
            location = 'Oulun jäähalli' } ]]
function Caption.fromGame(data, game)
	local home = data.byLiiga[game.teams[1]]
	local away = data.byLiiga[game.teams[2]]
	local match = (home and home.name or '?') .. '–' .. (away and away.name or '?')
	local where = game.cityIn ~= '' and game.cityIn or (game.city ~= '' and game.city or '')
	local template = '{people} Liigan ottelussa ' .. match
		.. (where ~= '' and (' ' .. where) or '') .. ' ' .. Caption.longDate(game.date) .. '.'
	return template, { headline = match, city = game.city, country = 'Finland', isoCountryCode = 'FI',
		location = game.rink }
end

-- name -> entry for everyone, the teams shown in the window first (a name in two presets means them)
function Caption.index(data, first, second)
	local index = {}
	local function add(team)
		for _, e in ipairs(team and team.people or {}) do
			if index[e.name] == nil then index[e.name] = e end
		end
	end
	add(first)
	add(second)
	add(data.referees)
	for _, t in ipairs(data.teams) do add(t) end
	return index
end

return Caption
