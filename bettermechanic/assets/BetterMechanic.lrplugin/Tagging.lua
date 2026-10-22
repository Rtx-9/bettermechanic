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

-- the people on a photo in the order they were tagged: IPTC Person Shown, else its keywords that are people
function Tagging.people(photo, index)
	local list = {}
	local ok, shown = pcall(photo.getFormattedMetadata, photo, 'personShown')
	for item in ((ok and shown) or ''):gmatch('[^,]+') do
		item = trim(item)
		if item ~= '' then list[#list + 1] = item end
	end
	if #list == 0 and index then
		for name in pairs(Tagging.names(photo)) do
			if index[name] then list[#list + 1] = name end
		end
		table.sort(list)
	end
	return list
end

local function without(list, name)
	local out = {}
	for _, item in ipairs(list) do
		if item ~= name then out[#out + 1] = item end
	end
	return out
end

local function field(photo, key)
	local ok, value = pcall(photo.getFormattedMetadata, photo, key)
	return ok and value or ''
end

--[[ Add `entry` to the photos, or take them off if every photo already has them. Returns 'added' or 'removed'
and how many captions were left alone because they're your own wording.

opts (all optional):
  template   caption with {people}: each photo's caption follows the people on it (see Caption.update)
  index      name -> entry, to write the people in the caption
  info       { headline, city, country, isoCountryCode, location }: filled in where the photo has none ]]
function Tagging.toggle(catalog, photos, entry, opts)
	opts = opts or {}
	local Caption = require 'Caption'
	local all = #photos > 0
	for _, photo in ipairs(photos) do
		if not Tagging.names(photo)[entry.name] then
			all = false
			break
		end
	end
	local kept = 0
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
			local before = Tagging.people(photo, opts.index)
			local after = without(before, entry.name)
			if all then
				photo:removeKeyword(kw)
			else
				photo:addKeyword(kw)
				for _, e in ipairs(extras) do photo:addKeyword(e) end
				after[#after + 1] = entry.name
			end
			pcall(photo.setRawMetadata, photo, 'personShown', table.concat(after, ', '))
			if opts.template and opts.template ~= '' then
				local index = opts.index or {}
				local caption = Caption.update(field(photo, 'caption'), opts.template, Caption.people(before, index),
					Caption.people(after, index))
				if caption then
					photo:setRawMetadata('caption', caption)
				else
					kept = kept + 1
				end
			end
			if opts.info and not all then
				for key, value in pairs(opts.info) do
					if value ~= '' and field(photo, key) == '' then
						pcall(photo.setRawMetadata, photo, key, value)
					end
				end
			end
		end
	end, { timeout = 10 })
	return all and 'removed' or 'added', kept
end

return Tagging
