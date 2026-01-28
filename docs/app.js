// Clean, single-file frontend script for album manager
// `APP_HOST` can be set by the embedding page (e.g. window.APP_HOST = 'https://appy.example.com')
// Leave empty for same-origin (default).
function apiUrl(path){ return (window.APP_HOST? window.APP_HOST.replace(/\/$/, '') : '') + path }

// Helper to trigger browser native download
function triggerNativeDownload(url) {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  setTimeout(() => document.body.removeChild(a), 100)
}

// Encode each path segment but preserve '/' separators so nested paths work
function fileUrlFor(rel){
  if(!rel) return apiUrl('/files/')
  return apiUrl('/files/' + rel.split('/').map(encodeURIComponent).join('/'))
}

function fileDownloadUrlFor(rel){
  // Construct a download-video API URL which accepts an encoded server-side
  // file path as `video_name`. Matches example:
  // /api/download-video?download=1&video_name=%2Fapp%2Foutputs%2F...%2Ffile.mp4
  const serverPath = '/app/outputs/' + rel
  return apiUrl('/api/download-video?download=1&video_name=' + encodeURIComponent(serverPath))
}

function filePreviewUrlFor(rel){
  // Return URL that forces inline preview (useful for Safari/iOS long-press Save)
  const serverPath = '/app/outputs/' + rel
  return apiUrl('/api/download-video?inline=1&video_name=' + encodeURIComponent(serverPath))
}

// Short helper for document.querySelector (used widely in this file)
function qs(sel){ return document.querySelector(sel) }

// Render recent tags as clickable buttons below a Tagify input.
function renderRecentTags(input, tags, tagify){
  try{
    if(!input) return
    // find or create container
    let container = input.parentNode && input.parentNode.querySelector('.recent-tags')
    if(!container){
      container = document.createElement('div')
      container.className = 'recent-tags'
      container.style = 'margin-top:6px;display:flex;flex-wrap:wrap;gap:6px'
      if(input.parentNode) input.parentNode.appendChild(container)
      else input.insertAdjacentElement('afterend', container)
    }
    container.innerHTML = ''
    if(!tags || !tags.length) return
    tags.forEach(t=>{
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.className = 'btn btn-sm btn-outline-secondary recent-tag-btn'
      btn.style.margin = '0'
      btn.textContent = t
      btn.onclick = (ev)=>{
        ev.preventDefault()
        try{
          if(tagify && typeof tagify.addTags === 'function'){
            tagify.addTags([t])
          } else {
            // fallback: append into input value if not Tagify
            if(input.value && input.value.trim()) input.value = input.value.trim() + ', ' + t
            else input.value = t
          }
        }catch(e){ console.warn('add recent tag failed', e) }
      }
      container.appendChild(btn)
    })
  }catch(e){ console.warn('renderRecentTags error', e) }
}

// Global TikTok upload modal (safe, standalone)
function showTikTokUploadModal(rel, name){
  let modal = document.getElementById('tiktokUploadModal')
  if(!modal){
    modal = document.createElement('div')
    modal.id = 'tiktokUploadModal'
    modal.style = 'position:fixed;left:0;top:0;right:0;bottom:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:9999'
    modal.innerHTML = `
      <div class="p-3" style="background:#fff;border-radius:8px;max-width:640px;width:100%;box-shadow:0 6px 30px rgba(0,0,0,0.28)">
        <h4 style="margin:0 0 12px">Upload to TikTok</h4>
        <div class="mb-2">
          <label class="form-label">Title</label>
          <input id="tt_title" class="form-control" />
        </div>
        <div class="mb-2">
          <label class="form-label">Tags</label>
          <input id="tt_tags" class="form-control" placeholder="type to get suggestions" />
        </div>
        <div class="mb-2">
          <label class="form-label">Cookies</label>
          <select id="tt_cookies" class="form-select">
            <option value="PhimTrung.json">PhimTrung.json</option>
            <option value="DemNgheChuyen.json">DemNgheChuyen.json</option>
            <option value="BungBu.json">BungBu.json</option>
          </select>
        </div>
        <div class="d-flex justify-content-end" style="gap:8px;margin-top:12px">
          <button id="tt_cancel" class="btn btn-secondary">Cancel</button>
          <button id="tt_confirm" class="btn btn-primary">Upload</button>
        </div>
        <div id="tt_status" style="margin-top:10px;font-size:0.9em;color:#444"></div>
      </div>`
    document.body.appendChild(modal)
  }

  const titleInput = document.querySelector('#tt_title')
  const tagsInput = document.querySelector('#tt_tags')
  const cookiesSelect = document.querySelector('#tt_cookies')
  const status = document.querySelector('#tt_status')
  if(titleInput) titleInput.value = (name || '').replace(/\.[^.]+$/, '')
  if(tagsInput) tagsInput.value = ''
  if(cookiesSelect) cookiesSelect.value = 'DemNgheChuyen.json'
  if(status) status.textContent = ''

  const resolveApi = (path)=>{ try{ if(typeof safeApiUrl === 'function') return safeApiUrl(path); return (window.APP_HOST? window.APP_HOST.replace(/\/$/, '') : '') + path }catch(e){ return path } }
  const apiFetch = (path, opts)=> fetch(typeof path === 'string' && path.startsWith('/') ? resolveApi(path) : path, opts)

  ;(async ()=>{
    try{
      const input = tagsInput
      if(!input) return
      if(input._tagify){ try{ input._tagify.removeAllTags(); input._tagify.destroy(); }catch(e){} }
      let whitelist = []
      try{ const r = await apiFetch('/api/tiktok_tags'); if(r && r.ok){ const j = await r.json(); whitelist = Array.isArray(j.tags)? j.tags : [] } }catch(e){}
      if(typeof window.Tagify === 'undefined'){
        await new Promise((resolve)=>{
          const s = document.createElement('script')
          s.src = 'https://cdn.jsdelivr.net/npm/@yaireo/tagify/dist/tagify.min.js'
          s.onload = resolve
          s.onerror = resolve
          document.head.appendChild(s)
        })
      }
      if(typeof window.Tagify !== 'undefined'){
        try{ input.classList.add('form-control') }catch(e){}
        const tagify = new Tagify(input, { enforceWhitelist: false, whitelist: (whitelist||[]).slice(0,10), dropdown:{enabled:1, maxItems:30, position:'text', highlightFirst:true}, delimiters:',' })
        input._tagify = tagify
        // render recent tags buttons (top 10 recent)
        try{ renderRecentTags(input, (whitelist||[]).slice(0,10), tagify) }catch(e){}
        let ajaxTimer = null
        tagify.on('add', async (e)=>{
          const val = e && e.detail && e.detail.data && e.detail.data.value ? e.detail.data.value.trim() : ''
          if(!val) return
          try{ if(whitelist.indexOf(val) === -1){ whitelist.push(val); await apiFetch('/api/tiktok_tags', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({tag: val})}) } }catch(err){ console.warn('persist tag failed', err) }
        })
        tagify.on('input', function(e){ tagify.whitelist = null; tagify.loading(true); if(ajaxTimer) clearTimeout(ajaxTimer); ajaxTimer = setTimeout(async ()=>{ try{ const r = await apiFetch('/api/tiktok_tags'); let list=[]; if(r&&r.ok){ const j=await r.json(); list=Array.isArray(j.tags)? j.tags:[] } const existing=(tagify.value||[]).map(v=>v.value); tagify.settings.whitelist = list.concat(existing); tagify.loading(false).dropdown.show(e.detail.value) }catch(err){ tagify.loading(false).dropdown.hide() } }, 250) })
      }
    }catch(err){ console.error('Tagify init error', err) }
  })()

  const cancelBtn = document.querySelector('#tt_cancel')
  if(cancelBtn) cancelBtn.onclick = ()=>{ try{ modal.remove() }catch(e){} }

  const confirmBtn = document.querySelector('#tt_confirm')
  if(confirmBtn) confirmBtn.onclick = async ()=>{
    const title = (document.querySelector('#tt_title') ? document.querySelector('#tt_title').value.trim() : '')
    let tags = []
    try{ const input = document.querySelector('#tt_tags'); if(input && input._tagify && Array.isArray(input._tagify.value)) tags = input._tagify.value.map(t=>t.value).filter(Boolean); else if(input) tags = input.value.split(',').map(t=>t.trim()).filter(Boolean) }catch(e){ tags=[] }
    try{ confirmBtn.disabled = true }catch(e){}
    if(status) status.textContent = 'Uploading...'
    try{
      try{ if(tags && tags.length){ await apiFetch('/api/tiktok_tags', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ tags: tags }) }) } }catch(err){ console.warn('Failed to persist tags before upload', err) }
      const params = new URLSearchParams(); params.set('video_path', rel); params.set('title', title); if(tags.length) params.set('tags', tags.join(',')); const cookies = document.querySelector('#tt_cookies') ? document.querySelector('#tt_cookies').value : ''; if(cookies) params.set('cookies', cookies)
      const controller = new AbortController(); const timeoutMs = 10 * 60 * 1000; const timeoutId = setTimeout(()=> controller.abort(), timeoutMs)
      const res = await apiFetch('/api/tiktok_upload?' + params.toString(), { method: 'GET', signal: controller.signal })
      clearTimeout(timeoutId)
      const j = await res.json().catch(()=>null)
      if(res.ok && j && j.ok){ if(status) status.textContent = 'Upload started successfully.'; setTimeout(()=>{ try{ modal.remove() }catch(e){} }, 800) }
      else { if(status) status.textContent = 'Upload failed: ' + (j && j.error ? j.error : res.statusText || 'error'); try{ confirmBtn.disabled = false }catch(e){} }
    }catch(err){ if(err && err.name === 'AbortError'){ if(status) status.textContent = 'Upload timed out after 10 minutes.' } else { if(status) status.textContent = 'Network error: ' + (err.message||err) } try{ confirmBtn.disabled = false }catch(e){} }
  }
}

// Fetch file as blob and trigger download via object URL. This avoids
// relying on the `download` attribute which is ignored for cross-origin
// links in many browsers.
async function downloadViaFetch(rel, filename, el){
  if(el && el.dataset && el.dataset.downloading) return
  function showTikTokUploadModal(rel, name){
    // Simple, robust modal for TikTok upload with Tagify suggestions.
    let modal = document.getElementById('tiktokUploadModal')
    if(!modal){
      modal = document.createElement('div')
      modal.id = 'tiktokUploadModal'
      modal.style = 'position:fixed;left:0;top:0;right:0;bottom:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:9999'
      modal.innerHTML = `
        <div style="background:#fff;padding:18px;border-radius:8px;max-width:560px;width:100%;box-shadow:0 6px 30px rgba(0,0,0,0.4)">
          <h3 style="margin:0 0 8px">Upload to TikTok</h3>
          <div style="margin-bottom:8px"><label>Title</label><input id="tt_title" style="width:100%;padding:8px;margin-top:4px;"/></div>
          <div style="margin-bottom:8px"><label>Tags</label><input id="tt_tags" style="width:100%;padding:8px;margin-top:4px;" placeholder="type to get suggestions"/></div>
          <div style="margin-bottom:8px"><label>Cookies</label>
            <select id="tt_cookies" style="width:100%;padding:8px;margin-top:4px;">
              <option value="PhimTrung.json">PhimTrung.json</option>
              <option value="DemNgheChuyen.json">DemNgheChuyen.json</option>
              <option value="BungBu.json">BungBu.json</option>
            </select>
          </div>
          <div style="text-align:right"><button id="tt_cancel" style="margin-right:8px">Cancel</button><button id="tt_confirm">Upload</button></div>
          <div id="tt_status" style="margin-top:8px;font-size:0.9em;color:#444"></div>
        </div>`
      document.body.appendChild(modal)
    }

    // Prefill values
    const titleInput = document.querySelector('#tt_title')
    const tagsInput = document.querySelector('#tt_tags')
    const cookiesSelect = document.querySelector('#tt_cookies')
    const status = document.querySelector('#tt_status')
    if(titleInput) titleInput.value = (name || '').replace(/\.[^.]+$/, '')
    if(tagsInput) tagsInput.value = ''
    if(cookiesSelect) cookiesSelect.value = 'DemNgheChuyen.json'
    if(status) status.textContent = ''

    // helpers to resolve API URL safely
    const resolveApi = (path)=>{ try{ if(typeof safeApiUrl === 'function') return safeApiUrl(path); return (window.APP_HOST? window.APP_HOST.replace(/\/$/, '') : '') + path }catch(e){ return path } }
    const apiFetch = (path, opts)=> fetch(typeof path === 'string' && path.startsWith('/') ? resolveApi(path) : path, opts)

    // initialize Tagify with server whitelist
    (async ()=>{
      try{
        const input = tagsInput
        if(!input) return
        if(input._tagify){ try{ input._tagify.removeAllTags(); input._tagify.destroy(); }catch(e){} }
        let whitelist = []
        try{ const r = await apiFetch('/api/tiktok_tags'); if(r && r.ok){ const j = await r.json(); whitelist = Array.isArray(j.tags)? j.tags : [] } }catch(e){}
        if(typeof window.Tagify === 'undefined'){
          await new Promise((resolve)=>{
            const s = document.createElement('script')
            s.src = 'https://cdn.jsdelivr.net/npm/@yaireo/tagify/dist/tagify.min.js'
            s.onload = resolve
            s.onerror = resolve
            document.head.appendChild(s)
          })
        }
        if(typeof window.Tagify !== 'undefined'){
        try{ input.classList.add('form-control') }catch(e){}
        const tagify = new Tagify(input, {
            enforceWhitelist: false,
            whitelist: whitelist,
            dropdown:{enabled:1, maxItems:30, position:'text', highlightFirst:true},
            delimiters:','
          })
          input._tagify = tagify

          // debounce timer for async suggestions
          let ajaxTimer = null

          tagify.on('add', async (e)=>{
            const val = e && e.detail && e.detail.data && e.detail.data.value ? e.detail.data.value.trim() : ''
            if(!val) return
            // persist new tag if it's not in the known whitelist
            try{
              const known = whitelist.indexOf(val) !== -1
              if(!known){ whitelist.push(val); await apiFetch('/api/tiktok_tags', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({tag: val})}) }
            }catch(err){ console.warn('Failed to persist tag', err) }
          })

          // suggestions: fetch server list on input and show dropdown
          tagify.on('input', function(e){
            tagify.whitelist = null
            tagify.loading(true)
            if(ajaxTimer) clearTimeout(ajaxTimer)
            ajaxTimer = setTimeout(async ()=>{
              try{
                const r = await apiFetch('/api/tiktok_tags')
                let list = []
                if(r && r.ok){ const j = await r.json(); list = Array.isArray(j.tags)? j.tags : [] }
                // server returns most-recent-first; show top 10 recent plus existing selected
                const recent = (list||[]).slice(0,10)
                const existing = (tagify.value||[]).map(v=>v.value)
                tagify.settings.whitelist = recent.concat(existing)
                try{ renderRecentTags(input, recent, tagify) }catch(e){}
                tagify.loading(false).dropdown.show(e.detail.value)
              }catch(err){
                tagify.loading(false).dropdown.hide()
              }
            }, 250)
          })

          // other useful listeners for debugging/UX
          tagify.on('remove', (e)=>{ console.log('tag removed', e.detail) })
          tagify.on('invalid', (e)=>{ console.log('invalid tag', e.detail) })
          tagify.on('dropdown:select', (e)=>{ console.log('dropdown select', e.detail) })
        }
      }catch(err){ console.error('Tagify init error', err) }
    })()

    // cancel handler
    const cancelBtn = document.querySelector('#tt_cancel')
    if(cancelBtn) cancelBtn.onclick = ()=>{ try{ modal.remove() }catch(e){} }

    // confirm/upload handler
    const confirmBtn = document.querySelector('#tt_confirm')
    if(confirmBtn) confirmBtn.onclick = async ()=>{
      const title = (document.querySelector('#tt_title') ? document.querySelector('#tt_title').value.trim() : '')
      // collect tags
      let tags = []
      try{
        const input = document.querySelector('#tt_tags')
        if(input && input._tagify && Array.isArray(input._tagify.value)) tags = input._tagify.value.map(t=>t.value).filter(Boolean)
        else if(input) tags = input.value.split(',').map(t=>t.trim()).filter(Boolean)
      }catch(e){ tags = [] }
      try{ confirmBtn.disabled = true }catch(e){}
      if(status) status.textContent = 'Uploading...'
      try{
        // Persist any new/edited tags before starting the upload
        try{
          if(tags && tags.length){
            await apiFetch('/api/tiktok_tags', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ tags: tags }) })
          }
        }catch(err){ console.warn('Failed to persist tags before upload', err) }

        const params = new URLSearchParams()
        params.set('video_path', rel)
        params.set('title', title)
        if(tags.length) params.set('tags', tags.join(','))
        const cookies = document.querySelector('#tt_cookies') ? document.querySelector('#tt_cookies').value : ''
        if(cookies) params.set('cookies', cookies)

        const controller = new AbortController()
        const timeoutMs = 10 * 60 * 1000
        const timeoutId = setTimeout(()=> controller.abort(), timeoutMs)
        const res = await apiFetch('/api/tiktok_upload?' + params.toString(), { method: 'GET', signal: controller.signal })
        clearTimeout(timeoutId)
        const j = await res.json().catch(()=>null)
        if(res.ok && j && j.ok){ if(status) status.textContent = 'Upload started successfully.'; setTimeout(()=>{ try{ modal.remove() }catch(e){} }, 800) }
        else { if(status) status.textContent = 'Upload failed: ' + (j && j.error ? j.error : res.statusText || 'error'); try{ confirmBtn.disabled = false }catch(e){} }
      }catch(err){
        if(err && err.name === 'AbortError'){ if(status) status.textContent = 'Upload timed out after 10 minutes.' }
        else { if(status) status.textContent = 'Network error: ' + (err.message||err) }
        try{ confirmBtn.disabled = false }catch(e){}
      }
    }
   }
  qs('#tt_tags').value = ''
  qs('#tt_cookies').value = 'DemNgheChuyen.json'
  const status = qs('#tt_status')
  status.textContent = ''
  // initialize Tagify for tags input and fetch latest whitelist each time
  (async function initTagify(){
    try{
      const input = qs('#tt_tags')
      if(!input) return
      // destroy previous instance if present
      if(input._tagify){ try{ input._tagify.removeAllTags(); input._tagify.destroy(); }catch(e){} }
      let whitelist = []
      try{ const r = await fetch(apiUrl('/api/tiktok_tags')); if(r.ok){ const j = await r.json(); whitelist = Array.isArray(j.tags)? j.tags : [] } }catch(e){ whitelist = [] }
      if(window.Tagify){
        try{ input.classList.add('form-control') }catch(e){}
        const tagify = new Tagify(input, { whitelist: whitelist, dropdown:{enabled:1, classname:'tags-look', maxItems:30, position:'text', highlightFirst:true}, delimiters:',' })
        input._tagify = tagify
        try{ renderRecentTags(input, (whitelist||[]).slice(0,10), tagify) }catch(e){}
        tagify.on('add', function(e){
          const val = e.detail && e.detail.data && e.detail.data.value ? e.detail.data.value.trim() : ''
          if(!val) return
          if(whitelist.indexOf(val) === -1){ whitelist.push(val); fetch(apiUrl('/api/tiktok_tags'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({tag: val})}).catch(()=>{}) }
        })
      }
    }catch(e){ /* ignore */ }
  })();

  qs('#tt_confirm').onclick = async () => {
    const title = qs('#tt_title').value.trim()
    // read tags from Tagify if present, otherwise from raw input
    let tags = []
    try{
      const input = qs('#tt_tags')
      if(input && input._tagify && Array.isArray(input._tagify.value)){
        tags = input._tagify.value.map(t=> t.value ).filter(Boolean)
      } else if(qs('#tt_tags')){
        tags = qs('#tt_tags').value.split(',').map(t=>t.trim()).filter(Boolean)
      }
    }catch(e){ tags = [] }
    qs('#tt_confirm').disabled = true
    status.textContent = 'Uploading...'
    try{
      const params = new URLSearchParams()
      params.set('video_path', rel)
      params.set('title', title)
      if(tags.length) params.set('tags', tags.join(','))
      const cookies = qs('#tt_cookies') ? qs('#tt_cookies').value : ''
      if(cookies) params.set('cookies', cookies)

      const controller = new AbortController()
      const timeoutMs = 10 * 60 * 1000 // 10 minutes
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

      const res = await fetch(apiUrl('/api/tiktok_upload') + '?' + params.toString(), { method: 'GET', signal: controller.signal })
      clearTimeout(timeoutId)
      let j = null
      try{ j = await res.json() }catch(e){ j = null }
      if(res.ok && j && j.ok){
        status.textContent = 'Upload started successfully.'
        setTimeout(()=>{ try{ modal.remove() }catch(e){} }, 800)
      } else {
        status.textContent = 'Upload failed: ' + (j && j.error ? j.error : res.statusText || 'error')
        qs('#tt_confirm').disabled = false
      }
    }catch(err){
      if(err && err.name === 'AbortError'){
        status.textContent = 'Upload timed out after 10 minutes.'
      } else {
        status.textContent = 'Network error: ' + (err.message||err)
      }
      qs('#tt_confirm').disabled = false
    }
  }
}

// Wait for selector to exist in DOM (polling). Returns the element or null after timeout.
function waitForSelector(sel, timeout = 5000, interval = 100){
  return new Promise((resolve) => {
    const start = Date.now()
    const iv = setInterval(() => {
      const el = document.querySelector(sel)
      if (el) {
        clearInterval(iv)
        resolve(el)
      } else if (Date.now() - start > timeout) {
        clearInterval(iv)
        resolve(null)
      }
    }, interval)
  })
}

let lastSearch = ''
let selectedFiles = new Set()

function updateDeleteSelectedButton(){
  const btn = qs('#btnDeleteSelected')
  if(!btn) return
  btn.disabled = selectedFiles.size === 0
}

function getFilter(){ const s = qs('#filterSelect'); return s ? s.value : 'all' }
function getSort(){ const s = qs('#sortSelect'); return s ? s.value : 'newest' }

function parentPath(p){
  if(!p) return ''
  const parts = p.split('/').filter(Boolean)
  if(parts.length <= 1) return ''
  parts.pop()
  return parts.join('/')
}

function updateUpButton(){ const btn = qs('#btnUp'); if(!btn) return; btn.disabled = !currentPath }

function formatDate(epoch){
  if(!epoch) return ''
  try{ const d = new Date(epoch * 1000); return d.toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'}) }
  catch(e){ return '' }
}

function sortFiles(files, sortKey){
  const copy = files.slice()
  if(sortKey === 'newest') copy.sort((a,b)=> (b.mtime||0) - (a.mtime||0))
  else if(sortKey === 'oldest') copy.sort((a,b)=> (a.mtime||0) - (b.mtime||0))
  else if(sortKey === 'name_asc') copy.sort((a,b)=> a.name.localeCompare(b.name))
  else if(sortKey === 'name_desc') copy.sort((a,b)=> b.name.localeCompare(a.name))
  else if(sortKey === 'type') copy.sort((a,b)=> (a.type||'').localeCompare(b.type||''))
  return copy
}

async function listPath(path=''){
  currentPath = path
  // clear selection when changing view
  selectedFiles.clear()
  updateDeleteSelectedButton()
  const foldersEl = qs('#folders')
  const filesEl = qs('#files')
  if(foldersEl) foldersEl.innerHTML = ''
  if(filesEl) filesEl.innerHTML = ''
  if(qs('#breadcrumb')) qs('#breadcrumb').textContent = path || '/'
  updateUpButton()

  const type = getFilter()
  const res = await fetch(apiUrl('/api/list?path=' + encodeURIComponent(path) + '&type=' + encodeURIComponent(type)))
  const data = await res.json()
  if(data.error){ alert(data.error); return }
  const folders = data.folders || []
  let files = data.files || []
  files = sortFiles(files, getSort())

  // render folders
  folders.forEach(f=>{
    const wrapper = document.createElement('div')
    wrapper.className = 'folder'
    // folder icon
    const icon = document.createElement('div')
    icon.className = 'folder-icon'
    icon.innerHTML = '<svg width="40" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 7C3 5.89543 3.89543 5 5 5H9L11 7H19C20.1046 7 21 7.89543 21 9V19C21 20.1046 20.1046 21 19 21H5C3.89543 21 3 20.1046 3 19V7Z" fill="#FBBF24" stroke="#D97706"/></svg>'
    wrapper.appendChild(icon)
    const nameSpan = document.createElement('span')
    nameSpan.className = 'folder-name'
    nameSpan.textContent = f.name
    // Open folder when clicking the name
    nameSpan.onclick = ()=>{ const next = path ? path + '/' + f.name : f.name; listPath(next) }

    // Also open folder when clicking anywhere on the folder wrapper for better UX on mobile
    wrapper.onclick = ()=>{ const next = path ? path + '/' + f.name : f.name; listPath(next) }

    const delBtn = document.createElement('button')
    delBtn.className = 'btn-del'
    delBtn.textContent = 'X'
    delBtn.title = 'Xóa album'
    // stopPropagation so clicking delete doesn't trigger wrapper onclick
    delBtn.onclick = async (ev)=>{ ev.stopPropagation(); if(!confirm('Xóa album "' + f.name + '" và tất cả nội dung?')) return; const rel = path ? path + '/' + f.name : f.name; const r = await fetch(apiUrl('/api/delete'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})}); const j=await r.json(); if(j.ok) listPath(path); else alert(j.error||'error') }

    const meta = document.createElement('div')
    meta.className = 'folder-meta'
    meta.appendChild(nameSpan)
    meta.appendChild(delBtn)
    wrapper.appendChild(meta)
    if(foldersEl) foldersEl.appendChild(wrapper)
  })

  // render files
  files.forEach(f=>{
    const card = document.createElement('div')
    card.className = 'card'
    const cb = document.createElement('input')
    cb.type = 'checkbox'
    cb.className = 'select-checkbox'
    cb.onclick = (e)=>{ e.stopPropagation(); if(cb.checked) selectedFiles.add(rel); else selectedFiles.delete(rel); updateDeleteSelectedButton() }
    card.appendChild(cb)
    const name = f.name
    const rel = path ? path + '/' + name : name
    const ext = name.split('.').pop().toLowerCase()
    const mtime = f.mtime

    const wrap = document.createElement('div')
    wrap.className = 'thumb-wrap'

    if(['png','jpg','jpeg','gif','bmp','webp'].includes(ext)){
      const img = document.createElement('img')
      img.src = fileUrlFor(rel)
      img.alt = name
      img.onclick = ()=> openPlayer(rel, name, 'image')
      wrap.appendChild(img)
    } else if(['mp4','webm','ogg'].includes(ext)){
      const vid = document.createElement('video')
      vid.className = 'thumb-video'
      // lazy-load: store preview URL in data-src and do not preload to avoid many initial requests
      vid.dataset.src = filePreviewUrlFor(rel)
      vid.muted = true
      vid.playsInline = true
      vid.preload = 'none'
      vid.loop = true
      vid.onclick = ()=> openPlayer(rel, name, 'video')
      // load on hover for quick preview
      vid.addEventListener('mouseenter', ()=>{
        try{
          if(!vid.src) vid.src = vid.dataset.src
          vid.play().catch(()=>{})
        }catch(e){}
      })
      vid.addEventListener('mouseleave', ()=>{
        try{ vid.pause(); vid.currentTime=0 }catch(e){}
        // optionally remove src to free bandwidth/memory for long lists
        try{ setTimeout(()=>{ if(vid && !vid.matches(':hover')){ vid.removeAttribute('src'); vid.load() } }, 1500) }catch(e){}
      })
      wrap.appendChild(vid)
      const overlay = document.createElement('div')
      overlay.className = 'play-overlay'
      overlay.textContent = '▶'
      overlay.onclick = ()=> openPlayer(rel, name, 'video')
      wrap.appendChild(overlay)
    } else if(['mp3','wav','m4a','aac','flac','oga'].includes(ext)){
      // audio file thumbnail — show an icon and play overlay; do not autoplay on hover
      const ico = document.createElement('div')
      ico.className = 'fileicon audioicon'
      ico.textContent = '♪'
      ico.onclick = ()=> openPlayer(rel, name, 'audio')
      wrap.appendChild(ico)
      const overlayA = document.createElement('div')
      overlayA.className = 'play-overlay'
      overlayA.textContent = '▶'
      overlayA.onclick = ()=> openPlayer(rel, name, 'audio')
      wrap.appendChild(overlayA)
    } else {
      const ico = document.createElement('div')
      ico.className = 'fileicon'
      ico.textContent = ext
      wrap.appendChild(ico)
    }

    const dateTxt = mtime ? formatDate(mtime) : ''
    const label = document.createElement('div')
    label.className = 'thumb-label'
    label.textContent = dateTxt
    wrap.appendChild(label)

    card.appendChild(wrap)

    const nameEl = document.createElement('div')
    nameEl.className = 'thumb-name'
    nameEl.textContent = name
    nameEl.title = name
    card.appendChild(nameEl)

    const caption = document.createElement('div')
    caption.className = 'caption'
    const dl = document.createElement('a')
    dl.href = fileDownloadUrlFor(rel)
    dl.download = name
    dl.className = 'icon-btn icon-download'
    dl.title = 'Download '
    dl.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 3v10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 11l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M21 21H3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    dl.addEventListener('click', (e)=>{
      e.preventDefault()
      triggerNativeDownload(fileDownloadUrlFor(rel))
    })
    const del = document.createElement('button')
    del.className = 'icon-btn icon-delete'
    del.title = 'Xóa'
    del.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 6h18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 6v12c0 1.1046.8954 2 2 2h4c1.1046 0 2-.8954 2-2V6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M10 11v6M14 11v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    del.onclick = async (ev)=>{ ev.stopPropagation(); if(!confirm('Xóa file "' + name + '"?')) return; const r = await fetch(apiUrl('/api/delete'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})}); const j=await r.json(); if(j.ok) listPath(path); else alert(j.error||'error') }
    caption.appendChild(dl)
    caption.appendChild(del)
    // Add TikTok upload button for video files in the normal files list
    if(['mp4','webm','ogg'].includes(ext)){
      try{
        const up = document.createElement('button')
        up.className = 'icon-btn icon-upload-tiktok'
        up.title = 'Upload to TikTok'
        up.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"><path d="M7 16a4 4 0 0 1 0-8 5 5 0 0 1 9.9 1.1A4 4 0 0 1 17 16H7z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 12v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 15l3-3 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        up.onclick = (ev)=>{ ev.stopPropagation(); showTikTokUploadModal(rel, name) }
        caption.appendChild(up)
      }catch(e){/* ignore */}
    }
    card.appendChild(caption)

    if(filesEl) filesEl.appendChild(card)
  })
}

qs('#createAlbumForm')?.addEventListener('submit', async (e)=>{
  e.preventDefault(); const form = e.target; const name = form.name.value.trim(); if(!name) return; const fd = new FormData(); fd.append('path', currentPath); fd.append('name', name); const res = await fetch(apiUrl('/api/create_album'),{method:'POST',body:fd}); const j = await res.json(); if(j.ok){ form.name.value=''; listPath(currentPath) } else alert(j.error||'error')
})

// Attach upload handler when the form/input is available to avoid race conditions
waitForSelector('#uploadForm', 7000).then((form) => {
  if (!form) return
  form.addEventListener('submit', async (e) => {
    e.preventDefault()
    const filesEl = document.querySelector('#uploadFiles')
    const files = filesEl ? filesEl.files : null
    if (!files || !files.length) return
    const fd = new FormData()
    fd.append('path', currentPath)
    for (const f of files) fd.append('files', f)
    const res = await fetch(apiUrl('/api/upload'), { method: 'POST', body: fd })
    const j = await res.json()
    if (j.saved) { if (filesEl) filesEl.value = ''; listPath(currentPath) } else alert(j.error || 'upload error')
  })
})

qs('#searchForm')?.addEventListener('submit', async (e)=>{ e.preventDefault(); const q = qs('#searchInput').value.trim(); lastSearch = q; if(!q) return listPath(currentPath); await performSearch(q, currentPath) })
qs('#clearSearch')?.addEventListener('click', (e)=>{ qs('#searchInput').value = ''; lastSearch = ''; listPath(currentPath) })
qs('#filterSelect')?.addEventListener('change', ()=>{ if(lastSearch) performSearch(lastSearch, currentPath); else listPath(currentPath) })
qs('#sortSelect')?.addEventListener('change', ()=>{ if(lastSearch) performSearch(lastSearch, currentPath); else listPath(currentPath) })

qs('#btnUp')?.addEventListener('click', ()=>{ const p = parentPath(currentPath); listPath(p) })

// Batch delete selected files
async function deleteSelected(){
  if(selectedFiles.size === 0) return
  if(!confirm('Xóa ' + selectedFiles.size + ' mục đã chọn?')) return
  const arr = Array.from(selectedFiles)
  const results = await Promise.all(arr.map(rel =>
    fetch(apiUrl('/api/delete'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})})
      .then(r=>r.json()).catch(e=>({error: e.message || String(e)}))
  ))
  const failed = []
  results.forEach((res,i)=>{ if(!res || !res.ok) failed.push({rel: arr[i], err: res && res.error ? res.error : JSON.stringify(res)}) })
  if(failed.length) alert('Một số mục không xóa được:\n' + failed.map(f=> f.rel + ': ' + f.err).join('\n'))
  selectedFiles.clear()
  updateDeleteSelectedButton()
  if(lastSearch) performSearch(lastSearch,currentPath); else listPath(currentPath)
}

qs('#btnDeleteSelected')?.addEventListener('click', deleteSelected)

async function performSearch(q, path=''){
  const foldersEl = qs('#folders')
  const filesEl = qs('#files')
  if(foldersEl) foldersEl.innerHTML=''
  if(filesEl) filesEl.innerHTML=''
  if(qs('#breadcrumb')) qs('#breadcrumb').textContent = `Search: "${q}" ${path?(' in '+path):''}`
  const url = apiUrl('/api/search?q=' + encodeURIComponent(q) + (path?('&path='+encodeURIComponent(path)):'') + '&type=' + encodeURIComponent(getFilter()))
  const res = await fetch(url)
  const data = await res.json()
  if(data.error){ alert(data.error); return }
  const results = data.results || []
  if(results.length===0){ if(filesEl) filesEl.textContent = 'Không tìm thấy'; return }

  const mapped = results.map(r=>({name:r.name, mtime:r.mtime, type:r.type, rel:r.rel}))
  const sorted = sortFiles(mapped, getSort())

  sorted.forEach(r=>{
    const card = document.createElement('div'); card.className='card'
    const name=r.name; const rel=r.rel; const ext = name.split('.').pop().toLowerCase(); const mtime = r.mtime
    const cb = document.createElement('input')
    cb.type = 'checkbox'
    cb.className = 'select-checkbox'
    cb.onclick = (e)=>{ e.stopPropagation(); if(cb.checked) selectedFiles.add(rel); else selectedFiles.delete(rel); updateDeleteSelectedButton() }
    card.appendChild(cb)
    const wrap = document.createElement('div'); wrap.className='thumb-wrap'
    if(['png','jpg','jpeg','gif','bmp','webp'].includes(ext)){
      const img=document.createElement('img'); img.src=fileUrlFor(rel); img.alt=name; img.onclick=()=>openPlayer(rel,name,'image'); wrap.appendChild(img)
    } else if(['mp4','webm','ogg'].includes(ext)){
      const vid=document.createElement('video'); vid.className='thumb-video'; vid.dataset.src=filePreviewUrlFor(rel); vid.muted=true; vid.playsInline=true; vid.preload='none'; vid.loop=true; vid.onclick=()=>openPlayer(rel,name,'video'); vid.addEventListener('mouseenter',()=>{ try{ if(!vid.src) vid.src = vid.dataset.src; vid.play().catch(()=>{}) }catch(e){} }); vid.addEventListener('mouseleave',()=>{ try{ vid.pause(); vid.currentTime=0 }catch(e){}; try{ setTimeout(()=>{ if(vid && !vid.matches(':hover')){ vid.removeAttribute('src'); vid.load() } },1500) }catch(e){} }); wrap.appendChild(vid); const overlay=document.createElement('div'); overlay.className='play-overlay'; overlay.textContent='▶'; overlay.onclick=()=>openPlayer(rel,name,'video'); wrap.appendChild(overlay)
    } else if(['mp3','wav','m4a','aac','flac','oga'].includes(ext)){
      const ico=document.createElement('div'); ico.className='fileicon audioicon'; ico.textContent='♪'; ico.onclick=()=>openPlayer(rel,name,'audio'); wrap.appendChild(ico); const overlay=document.createElement('div'); overlay.className='play-overlay'; overlay.textContent='▶'; overlay.onclick=()=>openPlayer(rel,name,'audio'); wrap.appendChild(overlay)
    } else { const ico=document.createElement('div'); ico.className='fileicon'; ico.textContent=ext; wrap.appendChild(ico) }
    const label=document.createElement('div'); label.className='thumb-label'; label.textContent = mtime ? formatDate(mtime) : ''; wrap.appendChild(label)
    card.appendChild(wrap)
    const nameEl=document.createElement('div'); nameEl.className='thumb-name'; nameEl.textContent=name; nameEl.title=name; card.appendChild(nameEl)
    const caption=document.createElement('div'); caption.className='caption'
    const dl=document.createElement('a')
    dl.href = fileDownloadUrlFor(rel)
    dl.download = name
    dl.textContent = 'Download'
    dl.className = 'link'
    dl.addEventListener('click', (e)=>{
      e.preventDefault()
      triggerNativeDownload(fileDownloadUrlFor(rel))
    })
    const del=document.createElement('button')
    del.textContent='Xóa'
    del.className='btn-del-file'
    del.onclick = async (ev)=>{ ev.stopPropagation(); if(!confirm('Xóa file "'+name+'"?')) return; const r = await fetch(apiUrl('/api/delete'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})}); const j = await r.json(); if(j.ok) performSearch(lastSearch,currentPath); else alert(j.error||'error') }
    caption.appendChild(dl); caption.appendChild(del);
    // Add TikTok upload button for video files
    if(['mp4','webm','ogg'].includes(ext)){
      try{
        const up = document.createElement('button')
        up.className = 'icon-btn icon-upload-tiktok'
        up.title = 'Upload to TikTok'
        up.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"><path d="M7 16a4 4 0 0 1 0-8 5 5 0 0 1 9.9 1.1A4 4 0 0 1 17 16H7z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 12v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 15l3-3 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        up.onclick = (ev)=>{ ev.stopPropagation(); showTikTokUploadModal(rel, name) }
        caption.appendChild(up)
      }catch(e){}
    }
    card.appendChild(caption)
    caption.appendChild(del)
    // Add TikTok upload button for video files (compact icon)
    if(['mp4','webm','ogg'].includes(ext)){
      try{
        const up = document.createElement('button')
        up.className = 'icon-btn icon-upload-tiktok'
        up.title = 'Upload to TikTok'
        up.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"><path d="M7 16a4 4 0 0 1 0-8 5 5 0 0 1 9.9 1.1A4 4 0 0 1 17 16H7z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 12v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 15l3-3 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        up.onclick = (ev)=>{ ev.stopPropagation(); showTikTokUploadModal(rel, name) }
        caption.appendChild(up)
      }catch(e){/* ignore */}
    }
  })
}

function openPlayer(rel, name, type){
  const modal = qs('#playerModal')
  const media = qs('#modalMedia')
  const modalVideo = qs('#modalVideo')
  const modalImage = qs('#modalImage')
  const modalAudio = qs('#modalAudio')
  const dl = qs('#modalDownload')
  if(!modal || !media) return
  // hide all media controls first
  try{ modalVideo.style.display = 'none'; modalVideo.pause(); modalVideo.removeAttribute('src'); modalVideo.load() }catch(e){}
  try{ modalImage.style.display = 'none'; modalImage.removeAttribute('src') }catch(e){}
  try{ modalAudio.style.display = 'none'; modalAudio.pause(); modalAudio.removeAttribute('src'); modalAudio.load() }catch(e){}
  // remove any previous play-fallback button
  const removeFallback = ()=>{ const btn = qs('#modalPlayFallback'); if(btn) btn.remove() }

  if(type === 'image'){
    modalImage.src = fileUrlFor(rel)
    modalImage.alt = name
    modalImage.style.display = ''
  } else if(type === 'video'){
    modalVideo.src = filePreviewUrlFor(rel)
    modalVideo.style.display = ''
    // ensure native controls visible
    modalVideo.controls = true
    modalVideo.playsInline = true
    modalVideo.preload = 'metadata'
  } else if(type === 'audio'){
    modalAudio.src = fileUrlFor(rel)
    modalAudio.style.display = ''
    modalAudio.controls = true
    try{ modalAudio.play().catch(()=>{}) }catch(e){}
  }


  dl.href = fileDownloadUrlFor(rel)
  dl.download = name
  // Use onclick assignment so repeated opens of the modal do not add
  // multiple event listeners (which caused multiple download triggers).
  dl.onclick = (e)=>{
    e.preventDefault()
    triggerNativeDownload(dl.href)
  }
  // Remove old iOS-specific buttons if they exist
  try{
    const existingSaveBtn = qs('#modalSaveToPhotos')
    if(existingSaveBtn) existingSaveBtn.remove()
    const existingOpenBtn = qs('#modalOpenInSafari')
    if(existingOpenBtn) existingOpenBtn.remove()
  }catch(e){}
  // Safari and Photos buttons removed as requested by user
  modal.setAttribute('aria-hidden','false')
}

function closePlayer(){
  const modal = qs('#playerModal')
  const modalVideo = qs('#modalVideo')
  const modalImage = qs('#modalImage')
  const modalAudio = qs('#modalAudio')
  if(!modal) return
  try{ if(modalVideo){ modalVideo.pause(); modalVideo.removeAttribute('src'); modalVideo.load(); modalVideo.style.display='none' } }catch(e){}
  try{ if(modalAudio){ modalAudio.pause(); modalAudio.removeAttribute('src'); modalAudio.load(); modalAudio.style.display='none' } }catch(e){}
  try{ if(modalImage){ modalImage.removeAttribute('src'); modalImage.style.display='none' } }catch(e){}
  modal.setAttribute('aria-hidden','true')
  try{ const p = qs('#modalPlaylist'); if(p) p.style.display = 'none' }catch(e){}
  try{ const s = qs('#modalPlaylistSidebar'); if(s) { s.classList.remove('open'); s.setAttribute('aria-hidden','true') } }catch(e){}
}

qs('#modalClose')?.addEventListener('click', closePlayer)
qs('#playerModal')?.addEventListener('click', (e)=>{ if(e.target.id === 'playerModal') closePlayer() })

// initial
listPath('')

// --- Handlers for Discord-like forms ---
async function postJson(path, body){
  try{
    const res = await fetch(apiUrl(path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    const text = await res.text()
    try{ const j = JSON.parse(text); alert('Response:\n' + JSON.stringify(j, null, 2).slice(0,2000)) }
    catch(e){ alert('Response:\n' + text.slice(0,2000)) }
  }catch(err){ alert('Network error: ' + (err.message||err)) }
}

// POST using query string parameters (unified endpoint expects Query params)
async function postQuery(path, params){
  const qs = Object.keys(params).map(k=> params[k]===undefined || params[k]===null ? '' : encodeURIComponent(k) + '=' + encodeURIComponent(String(params[k]))).filter(s=>s && !s.endsWith('=')).join('&')
  const url = path + (qs ? ('?' + qs) : '')
  try{
    const res = await fetch(apiUrl(url), { method: 'POST' })
    const text = await res.text()
    try{ const j = JSON.parse(text); alert('Response:\n' + JSON.stringify(j, null, 2).slice(0,2000)) }
    catch(e){ alert('Response:\n' + text.slice(0,2000)) }
  }catch(err){ alert('Network error: ' + (err.message||err)) }
}

// Load background audio list from backend and populate all bg_choice selects
async function loadBgAudioSelects(){
  try{
    const res = await fetch(apiUrl('/api/bgaudio_list'))
    if(!res.ok) return
    const j = await res.json()
    const files = (j && j.files) || []
    const selects = document.querySelectorAll('select[name="bg_choice"]')
    selects.forEach(sel => {
      // clear existing options except the first placeholder
      const cur = sel.querySelectorAll('option')
      const placeholder = cur.length ? cur[0].value : ''
      sel.innerHTML = ''
      const opt0 = document.createElement('option')
      opt0.value = ''
      opt0.textContent = '-- None --'
      sel.appendChild(opt0)
      files.forEach(f=>{
        const o = document.createElement('option')
        o.value = f.rel_path || f.name
        const kb = f.size ? Math.round(f.size/1024) + 'KB' : ''
        o.textContent = f.name + (kb ? (' — ' + kb) : '')
        sel.appendChild(o)
      })
    })
  }catch(e){ /* ignore */ }
}

qs('#videoTaskForm')?.addEventListener('submit', async (e)=>{
  e.preventDefault(); const f = e.target; const btn = f.querySelector('button[type="submit"]'); if(!f.story_url.value.trim()){ alert('Story URL is required'); return }
  try{ btn.disabled = true; const payload = { video_url: (f.video_urls.value||'').replace(/\n/g,',').trim(), story_url: f.story_url.value.trim(), Title: f.story_name.value.trim(), bg_choice: f.bg_choice.value.trim(), include_summary: f.include_summary.checked? 'true':'false', force_refresh: f.force_refresh.checked? 'true':'false' }
    // include voice if present
    if(f.voice && f.voice.value) payload.voice = f.voice.value
    // map names to unified endpoint params
    const params = {
      video_url: payload.video_url,
      story_url: payload.story_url,
      title: payload.Title || '',
      voice: payload.voice || '',
      bg_choice: payload.bg_choice || '',
      part_duration: f.part_duration && f.part_duration.value ? Number(f.part_duration.value) : undefined,
      start_from_part: f.start_from_part && f.start_from_part.value ? Number(f.start_from_part.value) : undefined,
      refresh_audio: f.refresh_audio ? (f.refresh_audio.checked? 'true' : 'false') : 'false',
      include_summary: payload.include_summary,
      parts: f.parts && f.parts.value ? f.parts.value.trim() : undefined,
    }
    await postQuery('/render_tiktok_large_video_unified', params)
  }finally{ btn.disabled = false }
})

qs('#clearCacheForm')?.addEventListener('submit', async (e)=>{
  e.preventDefault(); const f = e.target; const btn = f.querySelector('button[type="submit"]'); if(!f.story_url.value.trim()){ alert('Story URL is required'); return }
  try{ btn.disabled = true; const payload = { story_url: f.story_url.value.trim(), preserve_video_cache: (f.preserve_video_cache ? f.preserve_video_cache.value : 'true') }
    await postJson('/clear_story_cache', payload)
  }finally{ btn.disabled = false }
})

qs('#processSeriesForm')?.addEventListener('submit', async (e)=>{
  e.preventDefault(); const f = e.target; const btn = f.querySelector('button[type="submit"]'); if(!f.start_url.value.trim()){ alert('Start URL is required'); return }
  try{ btn.disabled = true; const payload = { start_url: f.start_url.value.trim(), titles: f.titles.value.trim(), max_episodes: f.max_episodes.value ? Number(f.max_episodes.value) : undefined, render_mode: f.render_mode.value.trim() }
    await postJson('/process_series', payload)
  }finally{ btn.disabled = false }
})

// new handlers for additional forms on standalone (check task / rename / delete)
qs('#checkTaskForm')?.addEventListener('submit', async (e)=>{
  e.preventDefault(); const f = e.target; const id = f.task_id.value.trim(); if(!id){ alert('Task ID required'); return }
  const r = await postJson('/task_status', { task_id: id })
  qs('#formsResponse').textContent = JSON.stringify(r, null, 2)
})

qs('#renameForm')?.addEventListener('submit', async (e)=>{
  e.preventDefault(); const f = e.target; const oldp = f.old.value.trim(); const newp = f.new.value.trim(); if(!oldp||!newp){ alert('Old and New required'); return }
  const r = await postJson('/api/rename', { old: oldp, new: newp })
  qs('#formsResponse').textContent = JSON.stringify(r, null, 2)
})

qs('#deletePathForm')?.addEventListener('submit', async (e)=>{
  e.preventDefault(); const f = e.target; const path = f.path.value.trim(); if(!path){ alert('Path required'); return }
  const r = await postJson('/api/delete', { path: path })
  qs('#formsResponse').textContent = JSON.stringify(r, null, 2)
})

// toggle forms panel visibility and open forms page
document.getElementById('toggleFormsBtn')?.addEventListener('click', ()=>{
  const el = document.getElementById('formsPanel'); if(!el) return; const show = (el.style.display === 'none' || !el.style.display)
  el.style.display = show ? 'block' : 'none'
  if(show) loadBgAudioSelects()
})
document.getElementById('openFormsPage')?.addEventListener('click', ()=>{
  // Open the local forms.html in the same folder as this index.html (avoid sandbox APP_HOST)
  try{
    window.open('forms.html', '_blank')
  }catch(e){
    // fallback to apiUrl if needed
    window.open(apiUrl('/forms.html').replace(/\/$/,'') || 'forms.html','_blank')
  }
})

// populate bg audio selects on initial load
loadBgAudioSelects()

// --- WebSocket for live task updates ---
let taskSocket = null
function wsUrl(path){
  if(window.APP_HOST && window.APP_HOST.startsWith('http')){
    return window.APP_HOST.replace(/^http/, 'ws') + path
  }
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://'
  return proto + location.host + path
}

function connectTaskWS(){
  try{
    const url = wsUrl('/ws/tasks')
    taskSocket = new WebSocket(url)
    taskSocket.onopen = ()=>{ console.log('ws connected') }
    taskSocket.onmessage = (ev)=>{
      try{
        const j = JSON.parse(ev.data)
        if(j && j.type === 'tasks') renderTasks(j.tasks || {})
      }catch(e){ console.warn('ws parse', e) }
    }
    taskSocket.onclose = ()=>{ console.log('ws closed, reconnecting in 2s'); setTimeout(connectTaskWS, 2000) }
    taskSocket.onerror = (e)=>{ console.warn('ws error', e); taskSocket.close() }
  }catch(e){ console.warn('ws connect failed', e); setTimeout(connectTaskWS, 2000) }
}

function renderTasks(tasks){
  const container = qs('#taskPanel') || qs('#liveTasks') || qs('#formsResponse')
  const dashboard = qs('#taskDashboard')
  if(!container && !dashboard) return
  try{
    const entries = Object.entries(tasks || {})
    if(entries.length === 0){
      if(container) container.innerHTML = '<div class="text-muted">No tasks</div>'
      if(dashboard) dashboard.innerHTML = '<div class="text-muted">No tasks</div>'
      return
    }
    const rows = entries.map(([id,t])=>{
      const title = t.title || t.Title || ''
      const status = t.status || ''
      const progress = t.progress || 0
      const pct = typeof progress === 'number' ? progress : 0
      const btnLabel = (status === 'cancelled' || status === 'completed') ? 'Resume' : 'Stop'
      const action = (btnLabel === 'Stop') ? 'stop' : 'resume'
      return `<div class="d-flex align-items-center justify-content-between mb-2 p-2 border rounded">
        <div style="flex:1">
          <div style="font-weight:700">${id} ${title?(' — '+escapeHtml(title)) : ''}</div>
          <div style="font-size:12px;color:#666">Status: ${escapeHtml(status)} — Progress: ${pct}%</div>
          <div class="progress mt-1" style="height:8px"><div class="progress-bar" role="progressbar" style="width:${pct}%"></div></div>
        </div>
        <div style="margin-left:8px">
          <button class="btn btn-sm btn-outline-danger" data-task="${escapeHtml(id)}" data-action="${action}">${btnLabel}</button>
        </div>
      </div>`
    }).join('\n')
    if(container) container.innerHTML = rows
    if(dashboard) dashboard.innerHTML = rows
    const applyHandlers = (el)=>{
      if(!el) return
      el.querySelectorAll('button[data-task]').forEach(b=> b.addEventListener('click', async (ev)=>{
        const taskId = b.dataset.task; const action = b.dataset.action
        try{ b.disabled = true; await fetch(apiUrl('/api/task_stop'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:taskId, action:action})}) }catch(e){ console.warn(e) }
        b.disabled = false
      }))
    }
    applyHandlers(container)
    applyHandlers(dashboard)
  }catch(e){ console.warn('renderTasks error', e) }
}

function escapeHtml(str){ return String(str||'').replace(/[&"'<>]/g, (c)=>({'&':'&amp;','"':'&quot;',"'":'&#39;','<':'&lt;','>':'&gt;'}[c])) }

setTimeout(connectTaskWS, 500)

// Dashboard panel toggle handlers (FAB)
document.getElementById('openDashboardFab')?.addEventListener('click', ()=>{
  const panel = document.getElementById('taskDashboardPanel')
  if(!panel) return
  panel.classList.toggle('open')
  panel.setAttribute('aria-hidden', panel.classList.contains('open') ? 'false' : 'true')
})
document.getElementById('closeDashboard')?.addEventListener('click', ()=>{
  const panel = document.getElementById('taskDashboardPanel')
  if(!panel) return
  panel.classList.remove('open')
  panel.setAttribute('aria-hidden','true')
})

// click outside to close dashboard
document.addEventListener('click', (e)=>{
  const panel = document.getElementById('taskDashboardPanel')
  const fab = document.getElementById('openDashboardFab')
  if(!panel || !panel.classList.contains('open')) return
  if(e.target === panel || panel.contains(e.target) || e.target === fab) return
  panel.classList.remove('open')
  panel.setAttribute('aria-hidden','true')
})
  
// --- Playlist playback + swipe controls for modal player ---
// Globals
window.__playlist = []
window.__playlistIndex = -1
window.__playlistMode = false

// Render playlist UI helper (exposed globally so playAtIndex can call it anytime)
window.renderPlaylistUI = function(list, currentIndex){
  try{
    // Render into both modal list and sidebar list (if present)
    const containers = [qs('#modalPlaylistList'), qs('#modalPlaylistListSidebar')].filter(Boolean)
    if(!containers.length) return
    if(!list || !list.length){ containers.forEach(c=> c.innerHTML = ''); return }
    containers.forEach(container => {
      container.innerHTML = ''
      list.forEach((it, idx)=>{
        const div = document.createElement('div')
        div.className = 'playlist-item' + (idx === currentIndex ? ' playing' : '')
        div.textContent = (idx+1) + '. ' + it.name
        div.dataset.idx = String(idx)
        // keep click handler simple; delegation also exists
        div.addEventListener('click', (ev)=>{ ev.stopPropagation(); playAtIndex(idx) })
        container.appendChild(div)
      })
      const cur = container.querySelector('.playlist-item.playing')
      if(cur){ try{ cur.scrollIntoView({block:'nearest', behavior:'smooth'}) }catch(e){} }
    })
  }catch(e){ console.warn('renderPlaylistUI', e) }
}

function buildPlaylistFromDOM(){
  try{
    const cards = document.querySelectorAll('#files .card')
    const items = []
    cards.forEach(c => {
      const nameEl = c.querySelector('.thumb-name')
      if(!nameEl) return
      const name = nameEl.textContent.trim()
      const ext = (name.split('.').pop() || '').toLowerCase()
      if(['mp4','webm','ogg'].includes(ext)){
        const rel = currentPath ? (currentPath + '/' + name) : name
        items.push({ rel, name })
      }
    })
    // sort by name (natural locale) to satisfy "sắp xếp theo tên"
    items.sort((a,b)=> a.name.localeCompare(b.name))
    return items
  }catch(e){ return [] }
}

function playAtIndex(idx){
  const list = window.__playlist || []
  if(!list || idx < 0 || idx >= list.length) return
  const item = list[idx]
  window.__playlistIndex = idx
  window.__playlistMode = true
  // reuse openPlayer to show modal and set video src
  try{ openPlayer(item.rel, item.name, 'video') }catch(e){}
  const v = qs('#modalVideo')
  if(v){
    v.addEventListener('loadedmetadata', function _playOnce(){ v.removeEventListener('loadedmetadata', _playOnce); try{ v.play().catch(()=>{}) }catch(e){} })
  }
  // update playlist UI highlight
  try{ if(typeof window.renderPlaylistUI === 'function') window.renderPlaylistUI(window.__playlist, window.__playlistIndex) }catch(e){}
}

function playNext(){
  if(!window.__playlist || window.__playlist.length === 0) return
  if(window.__playlistIndex < window.__playlist.length - 1) playAtIndex(window.__playlistIndex + 1)
  else window.__playlistMode = false
}

function playPrev(){
  if(!window.__playlist || window.__playlist.length === 0) return
  if(window.__playlistIndex > 0) playAtIndex(window.__playlistIndex - 1)
}

// Attach handlers when DOM ready
setTimeout(()=>{
  const playBtn = qs('#modalPlayPlaylist')
  const modalVideo = qs('#modalVideo')
  const modalMedia = qs('#modalMedia')
  if(playBtn){
    playBtn.addEventListener('click', ()=>{
      // build playlist from current folder and start from current file
      const list = buildPlaylistFromDOM()
      if(!list || !list.length) return alert('Không có video trong thư mục để phát.')
      window.__playlist = list
      // determine current filename from download link (modalDownload.download)
      const download = qs('#modalDownload')
      const fname = (download && download.download) ? download.download : null
      let startIdx = 0
      if(fname){ const found = list.findIndex(i=> i.name === fname); if(found >= 0) startIdx = found }
      playAtIndex(startIdx)
    })
  }

  if(modalVideo){
    modalVideo.addEventListener('ended', ()=>{ if(window.__playlistMode) playNext() })
  }

  // show/hide playlist list button
  const showBtn = qs('#modalShowPlaylist')
  if(showBtn){
    showBtn.addEventListener('click', ()=>{
      // Toggle sliding sidebar instead of modal list
      const sidebar = qs('#modalPlaylistSidebar')
      if(!sidebar) return
      try{
        if(!window.__playlist || !window.__playlist.length){
          const list = buildPlaylistFromDOM()
          if(!list || !list.length){ alert('Không có video trong thư mục để hiển thị.'); return }
          window.__playlist = list
          const download = qs('#modalDownload')
          const fname = (download && download.download) ? download.download : null
          let curIdx = 0
          if(fname){ const found = list.findIndex(i=> i.name === fname); if(found >= 0) curIdx = found }
          window.__playlistIndex = curIdx
          try{ if(typeof window.renderPlaylistUI === 'function') window.renderPlaylistUI(window.__playlist, window.__playlistIndex) }catch(e){}
        } else {
          try{ if(typeof window.renderPlaylistUI === 'function') window.renderPlaylistUI(window.__playlist, window.__playlistIndex) }catch(e){}
        }
      }catch(e){}
      const open = sidebar.classList.contains('open')
      if(open) { sidebar.classList.remove('open'); sidebar.setAttribute('aria-hidden','true') }
      else { sidebar.classList.add('open'); sidebar.setAttribute('aria-hidden','false') }
    })
  }

  // local bridge to global renderer (kept for backwards compatibility)
  function renderPlaylistUI(list, currentIndex){
    try{ if(typeof window.renderPlaylistUI === 'function') window.renderPlaylistUI(list, currentIndex) }catch(e){}
  }

  // initialize click delegation for playlist items (in case rendered later)
  // delegation for both modal list and sidebar list
  ;['#modalPlaylistList', '#modalPlaylistListSidebar'].forEach(sel => {
    const el = qs(sel)
    if(!el) return
    el.addEventListener('click', (e)=>{
      const item = e.target && e.target.closest && e.target.closest('.playlist-item')
      if(!item) return
      const idx = Number(item.dataset.idx)
      if(!Number.isNaN(idx)) playAtIndex(idx)
    })
  })

  // swipe gestures (mobile): swipe up -> next, swipe down -> prev
  if(modalMedia){
    let touchStartY = null
    modalMedia.addEventListener('touchstart', (e)=>{ try{ touchStartY = e.changedTouches[0].clientY }catch(_){} }, {passive:true})
    modalMedia.addEventListener('touchend', (e)=>{
      try{
        const y = e.changedTouches[0].clientY
        if(touchStartY === null) return
        const dy = y - touchStartY
        if(Math.abs(dy) < 40) return
        if(dy < 0){ /* swipe up */ if(window.__playlistMode) playNext(); else { /* if not in playlist, try building and play next */ const list = buildPlaylistFromDOM(); const cur = qs('#modalDownload') && qs('#modalDownload').download; if(list.length){ const found = list.findIndex(i=> i.name === cur); if(found >= 0) { window.__playlist = list; playAtIndex(found+1) } } } }
        else { /* swipe down */ if(window.__playlistMode) playPrev(); else { const list = buildPlaylistFromDOM(); const cur = qs('#modalDownload') && qs('#modalDownload').download; if(list.length){ const found = list.findIndex(i=> i.name === cur); if(found > 0) { window.__playlist = list; playAtIndex(found-1) } } } }
      }catch(e){}
      touchStartY = null
    }, {passive:true})
  }

  // sidebar close button
  const sidebarHide = qs('#modalPlaylistHide')
  if(sidebarHide){ sidebarHide.addEventListener('click', ()=>{ const s = qs('#modalPlaylistSidebar'); if(s){ s.classList.remove('open'); s.setAttribute('aria-hidden','true') } }) }
}, 400)

