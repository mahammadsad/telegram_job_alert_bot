import {describe,expect,it,vi} from 'vitest'
import {render,screen} from '@testing-library/react'
import {MemoryRouter,Route,Routes} from 'react-router-dom'
vi.mock('../lib/supabase',()=>({supabase:{auth:{getUser:()=>Promise.resolve({data:{user:null}})},from:vi.fn()}}))
import {AdminGuard} from './AdminGuard'
describe('AdminGuard',()=>{it('redirects unauthenticated visitors',async()=>{render(<MemoryRouter initialEntries={['/admin']}><Routes><Route path="/admin" element={<AdminGuard><p>secret</p></AdminGuard>}/><Route path="/admin/login" element={<p>login</p>}/></Routes></MemoryRouter>);expect(await screen.findByText('login')).toBeInTheDocument();expect(screen.queryByText('secret')).not.toBeInTheDocument()})})
