--[[ Tagging the photos selected in Lightroom: a keyword with the person's name (plus the team's keywords), and
the IPTC Extension "Person Shown" field, the same fields the BetterMechanic app writes. ]]

local LrDate = import 'LrDate'

local Tagging = {}

local function trim(s)
	return (s:gsub('^%s+', ''):gsub('%s+$', ''))
end

-- the selected photos; none (rather than the whole filmstrip) when nothing is selected
function Tagging.selection(catalog)
	if not catalog:getTargetPhoto() then
		return {}
	end
	return catalog:getTargetPhotos()
end

function Tagging.names(photo)
	local names = {}
	for _, kw in ipairs(photo:getRawMetadata('keywords') or {}) do
		names[kw:getName()] = true
	end
	return names
end

-- how many of the selected photos (up to `limit`) have each keyword, and how many were looked at
function Tagging.counts(photos, limit)
	local counts, n = {}, math.min(#photos, limit or #photos)
	for i = 1, n do
		for name in pairs(Tagging.names(photos[i])) do
			counts[name] = (counts[name] or 0) + 1
		end
	end
	return counts, n
end

-- capture date of a photo as YYYY-MM-DD, or nil
function Tagging.day(photo)
	if not photo then return nil end
	local t = photo:getRawMetadata('dateTimeOriginal')
	if type(t) ~= 'number' then return nil end
	return LrDate.timeToUserFormat(t, '%Y-%m-%d')
end

function Tagging.setPersonShown(photo, name, add)
	return pcall(function()
		local list, seen = {}, false
		for item in (photo:getFormattedMetadata('personShown') or ''):gmatch('[^,]+') do
			item = trim(item)
			if item == name then
				seen = true
				if add then list[#list + 1] = item end
			elseif item ~= '' then
				list[#list + 1] = item
			end
		end
		if add and not seen then list[#list + 1] = name end
		photo:setRawMetadata('personShown', table.concat(list, ', '))
	end)
end

-- add `entry` to the photos, or take them off if every photo already has them; returns 'added' or 'removed'
function Tagging.toggle(catalog, photos, entry)
	local all = #photos > 0
	for _, photo in ipairs(photos) do
		if not Tagging.names(photo)[entry.name] then
			all = false
			break
		end
	end
	catalog:withWriteAccessDo('Tag ' .. entry.name, function()
		local kw = catalog:createKeyword(entry.name, {}, true, nil, true)
		local extras = {}
		if not all then
			for k in ((entry.team and entry.team.keywords) or ''):gmatch('[^,]+') do
				k = trim(k)
				if k ~= '' then extras[#extras + 1] = catalog:createKeyword(k, {}, true, nil, true) end
			end
		end
		for _, photo in ipairs(photos) do
			if all then
				photo:removeKeyword(kw)
			else
				photo:addKeyword(kw)
				for _, e in ipairs(extras) do photo:addKeyword(e) end
			end
			Tagging.setPersonShown(photo, entry.name, not all)
		end
	end, { timeout = 10 })
	return all and 'removed' or 'added'
end

return Tagging
