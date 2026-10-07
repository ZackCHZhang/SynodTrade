import { Avatar, Stack, Tooltip } from '@mui/material';
import { useConfigs } from '../api/hooks';
import { ROLE_LABEL, STAGE_INFO } from '../lib/labels';

/** Two letters from an agent id: `value_investor` → `VI`, `kelly_sizer` → `KS`. */
function initials(agentId: string): string {
  const words = agentId.split(/[_\-\s]+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** `avatar` and `role` of an agent, looked up in the config list (null while loading or unknown). */
export function useAgentInfo(agentId: string | null | undefined): { avatar?: string | null; role?: string } | null {
  const { data } = useConfigs();
  if (!agentId) return null;
  return data?.agents?.find((a) => a.name === agentId) ?? null;
}

/**
 * The agent's picture from its config (`avatar:`). Without one, or when the image cannot be
 * loaded, a placeholder with the agent's initials in its role colour.
 */
export function AgentAvatar({ agentId, size = 28, src, role }: { agentId: string; size?: number; src?: string | null; role?: string }) {
  const info = useAgentInfo(agentId);
  const color = STAGE_INFO[role ?? info?.role ?? '']?.color ?? '#9e9e9e';
  // `src` / `role` override the saved config (live preview while editing)
  const image = src !== undefined ? src : info?.avatar;
  return (
    <Avatar
      src={image || undefined}
      alt={agentId}
      sx={{ width: size, height: size, fontSize: size * 0.4, fontWeight: 600, bgcolor: color, '& img': { objectPosition: 'center 15%' } }}
      slotProps={{ img: { loading: 'lazy', referrerPolicy: 'no-referrer' } }}
    >
      {initials(agentId)}
    </Avatar>
  );
}

/** Avatar + agent id in one line, for tables and lists. */
export function AgentLabel({ agentId, size = 24, children }: { agentId: string; size?: number; children?: React.ReactNode }) {
  const info = useAgentInfo(agentId);
  const role = info?.role ? ROLE_LABEL[info.role] ?? info.role : null;
  return (
    <Stack direction="row" spacing={1} component="span" sx={{ alignItems: 'center', display: 'inline-flex', verticalAlign: 'middle' }}>
      <Tooltip title={role ? `${agentId} · ${role}` : agentId}>
        <span>
          <AgentAvatar agentId={agentId} size={size} />
        </span>
      </Tooltip>
      <span>{children ?? agentId}</span>
    </Stack>
  );
}
