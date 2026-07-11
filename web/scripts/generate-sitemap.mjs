import {writeFileSync} from 'node:fs'

const [owner, repository] = (process.env.GITHUB_REPOSITORY || '/').split('/')
const githubPagesUrl = owner && repository ? `https://${owner}.github.io/${repository}` : ''
const origin=(process.env.VITE_PUBLIC_WEBSITE_URL||githubPagesUrl||'https://example.invalid').replace(/\/$/,'')
const routes=['/','/notices','/deadlines','/search','/verification-policy','/about','/disclaimer','/privacy','/telegram']
const urls=routes.map(path=>`<url><loc>${origin}${path}</loc></url>`).join('')
writeFileSync(new URL('../public/sitemap.xml',import.meta.url),`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>\n`)
const basePath = new URL(origin).pathname.replace(/\/$/, '')
writeFileSync(new URL('../public/robots.txt',import.meta.url),`User-agent: *\nAllow: /\nDisallow: ${basePath}/admin\nSitemap: ${origin}/sitemap.xml\n`)
