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
  return apiUrl('/api/download-video_name?download=1&video_name=' + encodeURIComponent(serverPath))
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

let currentPath = ''

function qs(sel){ return document.querySelector(sel) }

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
      vid.src = fileUrlFor(rel)
      vid.muted = true
      vid.playsInline = true
      vid.preload = 'metadata'
      vid.loop = true
      vid.onclick = ()=> openPlayer(rel, name, 'video')
      vid.addEventListener('mouseenter', ()=>{ try{ vid.play() }catch(e){} })
      vid.addEventListener('mouseleave', ()=>{ try{ vid.pause(); vid.currentTime=0 }catch(e){} })
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
    dl.addEventListener('click', (e)=>{ e.preventDefault(); downloadViaFetch(rel, name, e.currentTarget) })
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

qs('#uploadForm')?.addEventListener('submit', async (e)=>{
  e.preventDefault(); const files = qs('#uploadFiles').files; if(!files.length) return; const fd = new FormData(); fd.append('path', currentPath); for(const f of files) fd.append('files', f); const res = await fetch(apiUrl('/api/upload'),{method:'POST',body:fd}); const j = await res.json(); if(j.saved){ qs('#uploadFiles').value=''; listPath(currentPath) } else alert(j.error||'upload error')
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
      const vid=document.createElement('video'); vid.className='thumb-video'; vid.src=fileUrlFor(rel); vid.muted=true; vid.playsInline=true; vid.preload='metadata'; vid.loop=true; vid.onclick=()=>openPlayer(rel,name,'video'); vid.addEventListener('mouseenter',()=>{ try{ vid.play() }catch(e){} }); vid.addEventListener('mouseleave',()=>{ try{ vid.pause(); vid.currentTime=0 }catch(e){} }); wrap.appendChild(vid); const overlay=document.createElement('div'); overlay.className='play-overlay'; overlay.textContent='▶'; overlay.onclick=()=>openPlayer(rel,name,'video'); wrap.appendChild(overlay)
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
    dl.addEventListener('click', (e)=>{ e.preventDefault(); downloadViaFetch(rel, name, e.currentTarget) })
    const del=document.createElement('button')
    del.textContent='Xóa'
    del.className='btn-del-file'
    del.onclick = async (ev)=>{ ev.stopPropagation(); if(!confirm('Xóa file "'+name+'"?')) return; const r = await fetch(apiUrl('/api/delete'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})}); const j = await r.json(); if(j.ok) performSearch(lastSearch,currentPath); else alert(j.error||'error') }
    caption.appendChild(dl); caption.appendChild(del); card.appendChild(caption)
    if(filesEl) filesEl.appendChild(card)
  })
}

function openPlayer(rel, name, type){
  const modal = qs('#playerModal')
  const media = qs('#modalMedia')
  const dl = qs('#modalDownload')
  if(!modal || !media) return
  media.innerHTML = ''
  // remove any previous play-fallback button
  const removeFallback = ()=>{ const btn = qs('#modalPlayFallback'); if(btn) btn.remove() }

  if(type === 'image'){
    const img = document.createElement('img')
    img.src = fileUrlFor(rel)
    img.alt = name
    media.appendChild(img)
  } else if(type === 'video'){
    const vid = document.createElement('video')
    vid.src = fileUrlFor(rel)
    vid.controls = true
    vid.autoplay = true
    vid.playsInline = true
    vid.style.maxWidth = '100%'
    media.appendChild(vid)
    setTimeout(()=>{ try{ vid.play().catch(()=>{}) }catch(e){} },120)
  } else if(type === 'audio'){
    const aud = document.createElement('audio')
    aud.src = fileUrlFor(rel)
    aud.controls = true
    aud.autoplay = true
    aud.style.width = '100%'
    media.appendChild(aud)
    // try autoplay; if blocked show fallback button
    setTimeout(async ()=>{
      try{
        await aud.play()
        removeFallback()
      }catch(err){
        // autoplay blocked — add a prominent play button
        const btn = document.createElement('button')
        btn.id = 'modalPlayFallback'
        btn.className = 'modal-play-btn'
        btn.textContent = 'Play'
        btn.onclick = async ()=>{ try{ await aud.play(); btn.remove() }catch(e){ alert('Không thể phát âm thanh') } }
        // place button after media
        media.appendChild(btn)
      }
    }, 150)
  }

  dl.href = fileDownloadUrlFor(rel)
  dl.download = name
  dl.onclick = (e)=>{ e.preventDefault(); downloadViaFetch(rel, name, e.currentTarget) }
  modal.setAttribute('aria-hidden','false')
}

function closePlayer(){ const modal=qs('#playerModal'); const media=qs('#modalMedia'); if(!modal||!media) return; const v=media.querySelector('video'); if(v){ try{ v.pause() }catch(e){} } media.innerHTML=''; modal.setAttribute('aria-hidden','true') }

qs('#modalClose')?.addEventListener('click', closePlayer)
qs('#playerModal')?.addEventListener('click', (e)=>{ if(e.target.id === 'playerModal') closePlayer() })

// initial
listPath('')
  

