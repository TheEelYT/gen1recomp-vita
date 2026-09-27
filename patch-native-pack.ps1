$ErrorActionPreference = 'Stop'

# ==========================================================================
# native_pack.lua
# ==========================================================================

$p = 'B:\gen1recomp\src\import\gba\native_pack.lua'
$s = [System.IO.File]::ReadAllText($p)

# --------------------------------------------------------------------------
# Add low-memory direct encoders.
# --------------------------------------------------------------------------

if ($s -notmatch 'local function encode_idx_direct') {
    $marker = '--- Write all native blobs for Island 1 extract.'

    if (-not $s.Contains($marker)) {
        throw 'native_pack.lua: writeExtract marker not found'
    }

    $helpers = @'
-- Vita low-memory encoder: build the final .idx blob one metatile at a time
-- instead of retaining midCount*256 Lua numbers for both layers.
local function encode_idx_direct(compositeFn, bundle, midList, flags)
  midList = midList or {}

  local midCount = #midList
  local atlasCols = 16
  local atlasRows = math.max(1, math.ceil(midCount / atlasCols))

  local parts = {
    NativePack.MAGIC_IDX,
    u8(NativePack.FORMAT_VERSION),
    u8(flags or 0),
    u16le(midCount),
    u16le(atlasCols),
    u16le(atlasRows),
  }

  for _, mid in ipairs(midList) do
    parts[#parts + 1] = u16le(mid)
  end

  for i, mid in ipairs(midList) do
    local idxBuf = compositeFn(bundle, mid)
    local bytes = {}

    for p = 1, 256 do
      bytes[p] = u8(idxBuf[p] or 0)
    end

    parts[#parts + 1] = table.concat(bytes)

    if _G.POKEPORT_VITA and i % 32 == 0 then
      idxBuf = nil
      bytes = nil
      collectgarbage("collect")
    end
  end

  return table.concat(parts), midCount, atlasCols, atlasRows
end

local function unpack_grid_cell(cell)
  if type(cell) == "number" then
    return
      cell % 1024,
      math.floor(cell / 1024) % 4,
      math.floor(cell / 4096) % 16
  end

  cell = cell or {}
  return cell.mid or 0, cell.coll or 0, cell.elev or 0
end

-- Encode a map directly from its packed cells. This avoids allocating another
-- { mid, coll, elev } Lua table for every cell and avoids three tiny strings
-- per cell in encodeMidLayout().
local function encode_grid_layout_direct(
    grid, border, bundle, indexForPair, mapWarps, behaviorOf, fromCell)

  local trueW = grid.padded_from and grid.padded_from.width or grid.width
  local trueH = grid.padded_from and grid.padded_from.height or grid.height
  local bw = border.width or 1
  local bh = border.height or 1

  local parts = {
    NativePack.MAGIC_MID,
    u8(NativePack.FORMAT_VERSION),
    u8((grid.padded_from and 1) or 0),
    u16le(grid.width),
    u16le(grid.height),
    u16le(trueW),
    u16le(trueH),
    u8(bw),
    u8(bh),
  }

  local borderMids = border.mids or { 0 }
  for i = 1, bw * bh do
    parts[#parts + 1] = u16le(borderMids[i] or 0)
  end

  local chunk = {}

  for i, cell in ipairs(grid.cells or {}) do
    local mid, rawColl, elev = unpack_grid_cell(cell)
    local coll = 0xff

    if fromCell and behaviorOf and bundle then
      local beh = behaviorOf(bundle, mid)
      coll = select(1, fromCell(mid, rawColl, beh, grid.kind))
    else
      local mi = indexForPair[mid]
      if mi and mi.coll ~= nil then
        coll = mi.coll
      else
        coll = rawColl
      end
    end

    local cx = (i - 1) % grid.width
    local cy = math.floor((i - 1) / grid.width)

    coll = NativePack.resolveLayoutColl(
      coll,
      rawColl,
      mapWarps and mapWarps[
        cy * NativePack.WARP_KEY_STRIDE + cx
      ]
    )

    chunk[#chunk + 1] =
      u16le(mid) .. u8(coll) .. u8(elev)

    if #chunk >= 256 then
      parts[#parts + 1] = table.concat(chunk)
      chunk = {}
    end
  end

  if #chunk > 0 then
    parts[#parts + 1] = table.concat(chunk)
  end

  return table.concat(parts)
end

'@

    $s = $s.Replace($marker, $helpers + $marker)
}


# --------------------------------------------------------------------------
# Replace writeExtract with low-memory implementation.
# --------------------------------------------------------------------------

$pattern = '(?ms)^function NativePack\.writeExtract\(.*?^end(?=\r?\n\r?\nNativePack\.bgr555ToRgb8)'

$rx = [regex]::new($pattern)
$count = $rx.Matches($s).Count

if ($count -ne 1) {
    throw "native_pack.lua: expected 1 writeExtract function, found $count"
}

$newWriteExtract = @'
function NativePack.writeExtract(
    cache, root, bundles, grids, borders, pairNames, midIndex,
    behaviorOf, fromCell, scriptMids, warpCells, progressCb)

  root = root or require("src.core.game3.cache_paths").CACHE_ROOT
  local NativeRoot = root .. "/native"

  local manifest = {
    native_version = Versions.NATIVE_VERSION or 1,
    pairs = {},
    layouts = {},
  }

  local pairCount = #(pairNames or {})
  local layoutCount = 0

  for _ in pairs(grids or {}) do
    layoutCount = layoutCount + 1
  end

  -- +1 for manifest/finalization.
  local totalWork = math.max(pairCount + layoutCount + 1, 1)

  local function report(label, done)
    if progressCb then
      progressCb(label, done or 0, totalWork)
    end
  end

  -- -----------------------------------------------------------------------
  -- Tileset pair atlases.
  --
  -- On Vita, encode under/over independently and immediately write each
  -- blob. Do not retain two giant Lua-number pixel arrays simultaneously.
  -- -----------------------------------------------------------------------

  for pairIndex, pairName in ipairs(pairNames or {}) do
    report(
      string.format("pairs %d/%d: %s", pairIndex, pairCount, pairName),
      pairIndex - 1
    )

    local bundle = bundles[pairName]

    if bundle then
      local midList =
        NativePack.collectMidsForPair(
          grids, borders, pairName, scriptMids
        )

      local pairDir = NativeRoot .. "/" .. pairName

      local underBlob, midCount, atlasCols, atlasRows =
        encode_idx_direct(
          Metatile.compositeIndexedUnder,
          bundle,
          midList,
          NativePack.FLAG_LAYERED
        )

      cache:write(pairDir .. "/mids.idx", underBlob)

      underBlob = nil

      if _G.POKEPORT_VITA then
        collectgarbage("collect")
      end

      local overBlob =
        encode_idx_direct(
          Metatile.compositeIndexedOver,
          bundle,
          midList,
          NativePack.FLAG_LAYERED
        )

      cache:write(pairDir .. "/mids_over.idx", overBlob)

      overBlob = nil

      if _G.POKEPORT_VITA then
        collectgarbage("collect")
      end

      local palBlob = NativePack.encodePalettes(bundle.mapPals)
      cache:write(pairDir .. "/palettes.bin", palBlob)

      manifest.pairs[pairName] = {
        midCount = midCount,
        atlasCols = atlasCols,
        atlasRows = atlasRows,
        layered = true,
      }

      palBlob = nil
      midList = nil
      bundle = nil

      if _G.POKEPORT_VITA then
        collectgarbage("collect")
      end
    end
  end

  -- -----------------------------------------------------------------------
  -- Map layouts.
  --
  -- Encode directly from packed cells instead of allocating a second Lua
  -- table containing one {mid,coll,elev} table per map cell.
  -- -----------------------------------------------------------------------

  local layoutIndex = 0

  for mapId, grid in pairs(grids or {}) do
    layoutIndex = layoutIndex + 1

    report(
      string.format(
        "layouts %d/%d: %s",
        layoutIndex,
        layoutCount,
        tostring(mapId)
      ),
      pairCount + layoutIndex - 1
    )

    local pairName = grid.pair or "sevii_outdoor"
    local bundle = bundles[pairName]
    local indexForPair = midIndex and midIndex[pairName] or {}
    local mapWarps =
      warpCells and warpCells[grid.altOwner or mapId] or nil

    local border =
      borders and borders[mapId]
      or { width = 1, height = 1, mids = { 0 } }

    local blob = encode_grid_layout_direct(
      grid,
      border,
      bundle,
      indexForPair,
      mapWarps,
      behaviorOf,
      fromCell
    )

    cache:write(
      NativeRoot .. "/layouts/" .. mapId .. ".mid",
      blob
    )

    blob = nil

    if not grid.altLayoutId then
      manifest.layouts[mapId] = {
        pair = pairName,
        width = grid.width,
        height = grid.height,
        file = "layouts/" .. mapId .. ".mid",
      }
    end

    if _G.POKEPORT_VITA and layoutIndex % 8 == 0 then
      collectgarbage("collect")
    end
  end

  report("manifest", pairCount + layoutCount)

  local lines = {
    "return {\n",
    ("  native_version = %d,\n"):format(manifest.native_version),
    "  pairs = {\n",
  }

  for _, pairName in ipairs(pairNames or {}) do
    local p = manifest.pairs[pairName]

    if p then
      lines[#lines + 1] =
        ("    [%q] = { midCount = %d, atlasCols = %d, atlasRows = %d, layered = true },\n")
        :format(
          pairName,
          p.midCount,
          p.atlasCols,
          p.atlasRows
        )
    end
  end

  lines[#lines + 1] = "  },\n  layouts = {\n"

  local mapIds = {}

  for mapId in pairs(manifest.layouts) do
    mapIds[#mapIds + 1] = mapId
  end

  table.sort(mapIds)

  for _, mapId in ipairs(mapIds) do
    local L = manifest.layouts[mapId]

    lines[#lines + 1] =
      ("    [%q] = { pair = %q, width = %d, height = %d, file = %q },\n")
      :format(
        mapId,
        L.pair,
        L.width,
        L.height,
        L.file
      )
  end

  lines[#lines + 1] = "  },\n}\n"

  cache:write(
    NativeRoot .. "/manifest.lua",
    table.concat(lines)
  )

  report("done", totalWork)

  return manifest
end
'@

$s = $rx.Replace($s, $newWriteExtract, 1)

[System.IO.File]::WriteAllText(
    $p,
    $s,
    [System.Text.UTF8Encoding]::new($false)
)


# ==========================================================================
# extract_island1.lua - forward native_pack progress
# ==========================================================================

$p = 'B:\gen1recomp\src\import\gba\extract_island1.lua'
$s = [System.IO.File]::ReadAllText($p)

if ($s -notmatch '"native_pack: " \.\. tostring\(label\)') {
    $old = '    Tileset.behaviorOf, Collision.fromCell, scriptMids, warpCells)'

    if (-not $s.Contains($old)) {
        throw 'extract_island1.lua: NativePack.writeExtract argument tail not found'
    }

    $new = @'
    Tileset.behaviorOf, Collision.fromCell, scriptMids, warpCells,
    function(label, cur, total)
      progress(
        progressCb,
        6,
        "native_pack: " .. tostring(label),
        cur,
        total
      )
    end)
'@

    $s = $s.Replace($old, $new)
}

[System.IO.File]::WriteAllText(
    $p,
    $s,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host 'Low-memory native_pack patch applied successfully.'