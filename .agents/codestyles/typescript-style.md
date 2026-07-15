# React + TypeScript + Vite Style Guide

## Core Philosophy

- **Component composition over inheritance**
- **Type safety first** - Leverage TypeScript
- **Explicit over implicit** - Clear data flow
- **Performance by default** - Memoization, code splitting

## Critical Rules (Merge-blocking)

- No `any` types without explicit justification
- All props must be typed with interfaces
- No inline styles - use CSS modules or styled-components
- No console.log in production code
- All async operations must handle errors

## TypeScript Standards

```typescript
// PREFERRED: Interface for props
interface ButtonProps {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary';
  disabled?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  label,
  onClick,
  variant = 'primary',
  disabled = false,
}) => {
  return (
    <button
      className={`btn btn-${variant}`}
      onClick={onClick}
      disabled={disabled}
    >
      {label}
    </button>
  );
};
```

## Component Patterns

### Functional Components with Hooks

```typescript
import { useState, useEffect } from 'react';

interface UserProfileProps {
  userId: string;
}

interface User {
  id: string;
  name: string;
  email: string;
}

export const UserProfile: React.FC<UserProfileProps> = ({ userId }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const fetchUser = async () => {
      try {
        setLoading(true);
        const response = await fetch(`/api/users/${userId}`);
        if (!response.ok) throw new Error('Failed to fetch user');
        const data = await response.json();
        setUser(data);
      } catch (err) {
        setError(err instanceof Error ? err : new Error('Unknown error'));
      } finally {
        setLoading(false);
      }
    };

    fetchUser();
  }, [userId]);

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;
  if (!user) return null;

  return (
    <div className="user-profile">
      <h2>{user.name}</h2>
      <p>{user.email}</p>
    </div>
  );
};
```

### Custom Hooks

```typescript
interface UseApiResult<T> {
    data: T | null;
    loading: boolean;
    error: Error | null;
    refetch: () => Promise<void>;
}

export const useApi = <T>(url: string): UseApiResult<T> => {
    const [data, setData] = useState<T | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    const fetchData = async () => {
        try {
            setLoading(true);
            setError(null);
            const response = await fetch(url);
            if (!response.ok) throw new Error(`HTTP error ${response.status}`);
            const result = await response.json();
            setData(result);
        } catch (err) {
            setError(err instanceof Error ? err : new Error("Unknown error"));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, [url]);

    return { data, loading, error, refetch: fetchData };
};
```

## Performance Optimization

```typescript
import { memo, useMemo, useCallback } from 'react';

// Memoize component
export const ListItem = memo<ListItemProps>(({ id, title, onClick }) => {
  const handleClick = useCallback(() => {
    onClick(id);
  }, [id, onClick]);

  return <div onClick={handleClick}>{title}</div>;
});

// Memoize expensive computation
const sortedItems = useMemo(() => {
  return [...items].sort((a, b) => a.title.localeCompare(b.title));
}, [items]);
```

## Anti-Patterns

### Prop Drilling

```typescript
// WRONG: Passing props through many levels
<GrandParent user={user}>
  <Parent user={user}>
    <Child user={user} />
  </Parent>
</GrandParent>

// CORRECT: Use Context
<UserContext.Provider value={user}>
  <GrandParent>
    <Parent>
      <Child />
    </Parent>
  </GrandParent>
</UserContext.Provider>
```

### Mutating State

```typescript
// WRONG
items.push(4);
setItems(items);

// CORRECT
setItems([...items, 4]);
```

## Validation

```bash
npm run type-check  # TypeScript
npm run lint        # ESLint
npm run format      # Prettier
npm run test        # Vitest
```

## Accessibility

- Use semantic HTML (`<button>`, `<nav>`, `<main>`)
- Provide `aria-label` for icon-only buttons
- Ensure keyboard navigation works
- Maintain proper heading hierarchy
- Include alt text for images
- Use proper color contrast (WCAG AA)
