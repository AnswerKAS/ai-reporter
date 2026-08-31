export interface User {
  id: string
  username: string
  role: 'admin' | 'user'
  createdAt: string
}

export interface GroupMember {
  id: string
  username: string
  role: string
}

export interface Group {
  id: string
  name: string
  createdAt: string
  members: GroupMember[]
}

export interface AccessEntry {
  reportSlug: string
  userId: string | null
  groupId: string | null
  username: string | null
  groupName: string | null
}

export const TOKEN_KEY = 'ai-reporter-token'