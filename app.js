// Clean, single-file frontend script for album manager
// `APP_HOST` can be set by the embedding page (e.g. window.APP_HOST = 'https://appy.example.com')
// Leave empty for same-origin (default).
const APP_HOST = (window.APP_HOST || '').replace(/\/$/, '')
function apiUrl(path){ return (APP_HOST || '') + path }

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

// Fetch file as blob and trigger download via object URL. This avoids
// relying on the `download` attribute which is ignored for cross-origin
// links in many browsers.
async function downloadViaFetch(rel, filename, el){
  if(el && el.dataset && el.dataset.downloading) return
  let prevText = null
  if(el){
    el.dataset.downloading = '1'
    prevText = el.textContent
    try{ el.textContent = 'Đang tải...' }catch(e){}
    try{ el.style.pointerEvents = 'none' }catch(e){}
    el.classList.add && el.classList.add('loading')
  }
  try{
    const res = await fetch(fileDownloadUrlFor(rel))
    if(!res.ok) throw new Error('Network error: ' + res.status)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.style.display = 'none'
    a.href = url
    a.download = filename || ''
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(()=> URL.revokeObjectURL(url), 5000)
  }catch(err){
    alert('Không thể tải file: ' + (err.message||err))
  }finally{
    if(el){
      try{ delete el.dataset.downloading }catch(e){ el.dataset.downloading = '' }
      try{ el.textContent = prevText }catch(e){}
      try{ el.style.pointerEvents = '' }catch(e){}
      el.classList.remove && el.classList.remove('loading')
    }
  }
}

// Trigger native browser download without fetching the whole file into memory.
// Uses a hidden iframe so the page is not navigated away and the browser
// will show the Save As dialog immediately when the server responds
// with Content-Disposition: attachment.
function triggerNativeDownload(url){
  try{
    const iframe = document.createElement('iframe')
    iframe.style.display = 'none'
    // add a cache-busting param to avoid reusing an existing iframe src
    iframe.src = url + (url.includes('?') ? '&' : '?') + '_dl=' + Date.now()
    document.body.appendChild(iframe)
    // remove after a minute to be safe
    setTimeout(()=>{ try{ iframe.remove() }catch(e){} }, 60 * 1000)
    return true
  }catch(e){
    // fallback: open in new tab/window
    try{ window.open(url, '_blank') }catch(e){}
    return false
  }
}

// Try to save a file to iOS Photos via Web Share API (if supported).
// Falls back to opening the video so user can long-press -> "Save Video".
async function saveToPhotos(rel, name){
  try{
    const url = fileDownloadUrlFor(rel).replace(/download=1(&|$)/, '')
    const res = await fetch(url)
    if(!res.ok) throw new Error('Network: ' + res.status)
    const blob = await res.blob()
    const file = new File([blob], name, { type: blob.type || 'video/mp4' })
    if(navigator.canShare && navigator.canShare({ files: [file] })){
      await navigator.share({ files: [file], title: name })
      return true
    }
    // Fallback: open in new tab/window so user can long-press and Save Video
    const objUrl = URL.createObjectURL(blob)
    const w = window.open(objUrl, '_blank')
    setTimeout(()=> URL.revokeObjectURL(objUrl), 60000)
    if(!w) alert('Mở video thất bại — cho phép popup hoặc dùng Long-press trên liên kết Download')
    return false
  }catch(err){
    alert('Không thể lưu vào Photos: ' + (err.message || err))
    return false
  }
}

let currentPath = ''

function qs(sel){ return document.querySelector(sel) }

// --- TikTok upload modal helper ---
function showTikTokUploadModal(rel, name){
  // create modal if missing
  let modal = qs('#tiktokUploadModal')
  if(!modal){
    modal = document.createElement('div')
    modal.id = 'tiktokUploadModal'
    modal.style = 'position:fixed;left:0;top:0;right:0;bottom:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:9999'
    modal.innerHTML = `
      <div style="background:#fff;padding:18px;border-radius:8px;max-width:560px;width:100%;box-shadow:0 6px 30px rgba(0,0,0,0.4)">
        <h3 style="margin:0 0 8px">Upload to TikTok</h3>
        <div style="margin-bottom:8px"><label>Title</label><input id="tt_title" style="width:100%;padding:8px;margin-top:4px;"/></div>
        <div style="margin-bottom:8px"><label>Tags (comma separated)</label><input id="tt_tags" style="width:100%;padding:8px;margin-top:4px;"/></div>
        <div style="text-align:right"><button id="tt_cancel" style="margin-right:8px">Cancel</button><button id="tt_confirm">Upload</button></div>
        <div id="tt_status" style="margin-top:8px;font-size:0.9em;color:#444"></div>
      </div>`
    document.body.appendChild(modal)
    qs('#tt_cancel').addEventListener('click', ()=>{ try{ modal.remove() }catch(e){} })
  }
  // prefill
  qs('#tt_title').value = name.replace(/\.[^.]+$/, '')
  qs('#tt_tags').value = ''
  const status = qs('#tt_status')
  status.textContent = ''
  qs('#tt_confirm').onclick = async () => {
    const title = qs('#tt_title').value.trim()
    const tags = qs('#tt_tags').value.split(',').map(t=>t.trim()).filter(Boolean)
    qs('#tt_confirm').disabled = true
    status.textContent = 'Uploading...'
    try{
      const res = await fetch(apiUrl('/api/tiktok_upload'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: rel, title: title, tags: tags})})
      const j = await res.json()
      if(res.ok && j && j.ok){
        status.textContent = 'Upload started successfully.'
        setTimeout(()=>{ try{ modal.remove() }catch(e){} }, 800)
      } else {
        status.textContent = 'Upload failed: ' + (j && j.error ? j.error : res.statusText || 'error')
        qs('#tt_confirm').disabled = false
      }
    }catch(err){
      status.textContent = 'Network error: ' + (err.message||err)
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
    const nameSpan = document.createElement('span')
    nameSpan.className = 'folder-name'
    nameSpan.textContent = f.name
    nameSpan.onclick = ()=>{ const next = path ? path + '/' + f.name : f.name; listPath(next) }

    const delBtn = document.createElement('button')
    delBtn.className = 'btn-del'
    delBtn.textContent = 'X'
    delBtn.title = 'Xóa album'
    delBtn.onclick = async (ev)=>{ ev.stopPropagation(); if(!confirm('Xóa album "' + f.name + '" và tất cả nội dung?')) return; const rel = path ? path + '/' + f.name : f.name; const r = await fetch(apiUrl('/api/delete'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})}); const j=await r.json(); if(j.ok) listPath(path); else alert(j.error||'error') }

    wrapper.appendChild(nameSpan)
    wrapper.appendChild(delBtn)
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
    dl.textContent = 'Download'
    dl.className = 'link'
    dl.addEventListener('click', (e)=>{
      e.preventDefault()
      // Let the browser handle the download via native navigation.
      // Use a hidden iframe so the page is not navigated away.
      triggerNativeDownload(fileDownloadUrlFor(rel))
    })
    const del = document.createElement('button')
    del.textContent = 'Xóa'
    del.className = 'btn-del-file'
    del.onclick = async (ev)=>{ ev.stopPropagation(); if(!confirm('Xóa file "' + name + '"?')) return; const r = await fetch(apiUrl('/api/delete'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})}); const j=await r.json(); if(j.ok) listPath(path); else alert(j.error||'error') }
    caption.appendChild(dl)
    caption.appendChild(del)
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
        up.textContent = 'Upload TikTok'
        up.className = 'btn-upload-tiktok'
        up.onclick = (ev)=>{ ev.stopPropagation(); showTikTokUploadModal(rel, name) }
        caption.appendChild(up)
      }catch(e){}
    }
    card.appendChild(caption)
    caption.appendChild(del)
    // Add TikTok upload button for video files
    if(['mp4','webm','ogg'].includes(ext)){
      try{
        const up = document.createElement('button')
        up.textContent = 'Upload TikTok'
        up.className = 'btn-upload-tiktok'
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
  // Add "Save to Photos" button for video on iOS (uses Web Share API or fallback)
  try{
    const existingSaveBtn = qs('#modalSaveToPhotos')
    if(existingSaveBtn) existingSaveBtn.remove()
    const existingOpenBtn = qs('#modalOpenInSafari')
    if(existingOpenBtn) existingOpenBtn.remove()
  }catch(e){}
  if(type === 'video'){
    const saveBtn = document.createElement('button')
    saveBtn.id = 'modalSaveToPhotos'
    saveBtn.className = 'btn-save-photos'
    saveBtn.textContent = 'Lưu vào Photos'
    saveBtn.onclick = async (ev)=>{
      ev.stopPropagation(); saveBtn.disabled = true; const ok = await saveToPhotos(rel, name); saveBtn.disabled = false; if(ok) {/* optional success UI */}
    }
    // place button next to download anchor if present
    try{ dl.parentNode && dl.parentNode.insertBefore(saveBtn, dl.nextSibling) }catch(e){ media.appendChild(saveBtn) }
    // Add "Open in Safari" button to open inline preview in a new tab (helpful on iOS)
    const openBtn = document.createElement('button')
    openBtn.id = 'modalOpenInSafari'
    openBtn.className = 'btn-open-safari'
    openBtn.textContent = 'Mở trong Safari'
    openBtn.onclick = (ev)=>{
      ev.stopPropagation()
      const url = filePreviewUrlFor(rel)
      window.open(url, '_blank')
    }
    try{ dl.parentNode && dl.parentNode.insertBefore(openBtn, saveBtn.nextSibling) }catch(e){ media.appendChild(openBtn) }
  }
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
document.getElementById('openFormsPage')?.addEventListener('click', ()=>{ window.open(apiUrl('/forms.html').replace(/\/$/,'') || 'forms.html','_blank') })

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
  
