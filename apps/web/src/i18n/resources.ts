/**
 * One JSON file per area and language under src/locales. English is the
 * source of truth for key types; Indonesian must carry the same keys
 * (src/i18n/resources.test.ts checks that).
 */
import en_admin from '@/locales/en/admin.json'
import en_auth from '@/locales/en/auth.json'
import en_backlog from '@/locales/en/backlog.json'
import en_board from '@/locales/en/board.json'
import en_common from '@/locales/en/common.json'
import en_contract from '@/locales/en/contract.json'
import en_home from '@/locales/en/home.json'
import en_item from '@/locales/en/item.json'
import en_pages from '@/locales/en/pages.json'
import en_settings from '@/locales/en/settings.json'
import en_shell from '@/locales/en/shell.json'
import id_admin from '@/locales/id/admin.json'
import id_auth from '@/locales/id/auth.json'
import id_backlog from '@/locales/id/backlog.json'
import id_board from '@/locales/id/board.json'
import id_common from '@/locales/id/common.json'
import id_contract from '@/locales/id/contract.json'
import id_home from '@/locales/id/home.json'
import id_item from '@/locales/id/item.json'
import id_pages from '@/locales/id/pages.json'
import id_settings from '@/locales/id/settings.json'
import id_shell from '@/locales/id/shell.json'

export const defaultNS = 'common'

export const resources = {
  en: {
    common: en_common,
    shell: en_shell,
    auth: en_auth,
    settings: en_settings,
    home: en_home,
    backlog: en_backlog,
    board: en_board,
    item: en_item,
    pages: en_pages,
    admin: en_admin,
    contract: en_contract,
  },
  id: {
    common: id_common,
    shell: id_shell,
    auth: id_auth,
    settings: id_settings,
    home: id_home,
    backlog: id_backlog,
    board: id_board,
    item: id_item,
    pages: id_pages,
    admin: id_admin,
    contract: id_contract,
  },
} as const
