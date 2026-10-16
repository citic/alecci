"""IR builder helpers shared by the compiler modules."""
from llvmlite import ir


class EntryAllocaBuilder(ir.IRBuilder):
    """IRBuilder whose ``alloca`` always lands in the function's entry block.

    An ``alloca`` emitted inside a loop body grows the stack on every iteration
    (a long-running ``while``/``for`` loop eventually overflows it), so all
    stack slots are hoisted to the entry block where they are allocated once.
    Use :func:`alloca_here` for the few allocations that must stay unique per
    dynamic execution (e.g. thread argument blocks that outlive the statement).
    """

    def alloca(self, typ, size=None, name=''):
        entry = self.function.entry_basic_block
        entry_builder = ir.IRBuilder(entry)
        entry_builder.position_at_start(entry)
        inst = entry_builder.alloca(typ, size, name)
        if self.block is entry:
            # llvmlite tracks the insertion point as an index into the block, and
            # the new instruction was inserted before it.
            self._anchor += 1
        return inst


def alloca_here(builder, typ, size=None, name=''):
    """Emit an alloca at the builder's current position (not hoisted)."""
    return ir.IRBuilder.alloca(builder, typ, size, name)
