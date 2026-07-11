import {writeFileSync} from 'node:fs'
const origin=(process.env.VITE_PUBLIC_WEBSITE_URL||'https://example.pages.dev').replace(/\/$/,'')
const routes=['/','/notices','/deadlines','/search','/verification-policy','/about','/disclaimer','/privacy','/telegram']
const urls=routes.map(path=>`<url><loc>${origin}${path}</loc></url>`).join('')
writeFileSync(new URL('../public/sitemap.xml',import.meta.url),`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>\n`)
